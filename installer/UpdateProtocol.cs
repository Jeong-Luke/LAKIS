using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

internal sealed class UpdateFile
{
    public string path { get; set; }
    public string url { get; set; }
    public string sha256 { get; set; }
}

internal sealed class UpdateManifest
{
    public int schema { get; set; }
    public string kind { get; set; }
    public string version { get; set; }
    public string minimum_version { get; set; }
    public string minimum_updater_version { get; set; }
    public string release_notes { get; set; }
    public List<UpdateFile> files { get; set; }
    public List<string> delete { get; set; }
    public Dictionary<string, object> runtime_bundle { get; set; }
}

internal static class UpdateProtocol
{
    // This is the executing engine's capability, not the installation's VERSION.
    internal const string EngineVersion = "8.0.0";
    internal const string BridgeVersion = "7.5.4";
    internal const string RuntimeBridgeVersion = "7.5.4.1";
    internal const int Schema = 2;
    internal static readonly string[] ManifestUrls = {
#if LAKIS_RUNTIME_BRIDGE
        // The intermediate installation still needs the 8.0.0 runtime,
        // even after the normal channel advances to application-only patches.
        "https://github.com/Jeong-Luke/LAKIS/releases/download/v8.0.0/update-v3-latest.json"
#else
        "https://raw.githubusercontent.com/Jeong-Luke/LAKIS/main/manifests/update-v3-latest.json",
        "https://cdn.jsdelivr.net/gh/Jeong-Luke/LAKIS@main/manifests/update-v3-latest.json"
#endif
    };

    internal static Version ParseVersion(string value)
    {
        Version version;
        if (!Regex.IsMatch(value ?? "", "^[0-9]+\\.[0-9]+\\.[0-9]+(?:\\.[0-9]+)?\\z") ||
            !Version.TryParse(value, out version))
            throw new InvalidDataException("업데이트 버전 형식이 올바르지 않습니다.");
        return version;
    }

    internal static int CompareVersions(string left, string right)
    {
        Version a = ParseVersion(left), b = ParseVersion(right);
        return new Version(a.Major, a.Minor, a.Build, Math.Max(0, a.Revision)).CompareTo(
            new Version(b.Major, b.Minor, b.Build, Math.Max(0, b.Revision)));
    }

    internal static UpdateManifest Read(string json)
    {
        try
        {
            var serializer = new JavaScriptSerializer();
            var raw = serializer.Deserialize<Dictionary<string, object>>(json);
            object schema;
            if (raw == null || !raw.TryGetValue("schema", out schema) ||
                !(schema is int) || (int)schema != Schema)
                throw new InvalidDataException("지원하지 않는 업데이트 명세입니다. 업데이터를 먼저 갱신해야 합니다.");
            // A bundle must never fall through to the ordinary file patcher.
            if (raw.ContainsKey("runtime_bundle") &&
                (!raw.ContainsKey("kind") || (string)raw["kind"] != "runtime-update"))
                throw new InvalidDataException("이 업데이터는 런타임 교체 명세를 지원하지 않습니다.");
            var manifest = serializer.Deserialize<UpdateManifest>(json);
            Validate(manifest);
            return manifest;
        }
        catch (InvalidDataException) { throw; }
        catch (ArgumentException error)
        {
            throw new InvalidDataException("업데이트 명세를 해석할 수 없습니다.", error);
        }
        catch (InvalidOperationException error)
        {
            throw new InvalidDataException("업데이트 명세를 해석할 수 없습니다.", error);
        }
    }

    private static void Validate(UpdateManifest manifest)
    {
        if (manifest == null || manifest.schema != Schema ||
            (manifest.kind != "file-patch" && manifest.kind != "runtime-update"))
            throw new InvalidDataException("지원하지 않는 업데이트 작업입니다.");
        ParseVersion(manifest.version);
        ParseVersion(manifest.minimum_version);
        ParseVersion(manifest.minimum_updater_version);
        if (CompareVersions(manifest.minimum_updater_version, EngineVersion) > 0)
            throw new InvalidDataException("이 업데이트에는 더 최신 업데이터가 필요합니다.");
        if (CompareVersions(manifest.minimum_version, BridgeVersion) < 0 ||
            CompareVersions(manifest.minimum_version, manifest.version) > 0)
            throw new InvalidDataException("중간 업데이트의 설치 버전 요구사항이 올바르지 않습니다.");
        if (manifest.files == null || manifest.delete == null)
            throw new InvalidDataException("업데이트 파일 목록이 없습니다.");
        if (manifest.kind == "runtime-update")
        {
            if (manifest.runtime_bundle == null || manifest.files.Count != 0 || manifest.delete.Count != 0)
                throw new InvalidDataException("런타임 교체와 개별 파일 변경을 함께 적용할 수 없습니다.");
            object product, version, schema, digest;
            var bundle = manifest.runtime_bundle;
            if (!bundle.TryGetValue("schema", out schema) || !(schema is int) || (int)schema != 2 ||
                !bundle.TryGetValue("product", out product) || !Equals(product, "LAKIS") ||
                !bundle.TryGetValue("version", out version) || !Equals(version, manifest.version) ||
                !bundle.TryGetValue("manifest_sha256", out digest) || !(digest is string) ||
                !Regex.IsMatch((string)digest, "^[a-fA-F0-9]{64}\\z"))
                throw new InvalidDataException("런타임 배포 명세가 일치하지 않습니다.");
        }
        else if (manifest.runtime_bundle != null)
            throw new InvalidDataException("개별 파일 업데이트에 런타임 교체가 포함되어 있습니다.");
        foreach (var file in manifest.files)
            if (file == null || String.IsNullOrWhiteSpace(file.path) ||
                String.IsNullOrWhiteSpace(file.url) ||
                !Regex.IsMatch(file.sha256 ?? "", "^[a-fA-F0-9]{64}\\z"))
                throw new InvalidDataException("업데이트 파일 정보가 올바르지 않습니다.");
    }

    internal static void ValidateForInstallation(UpdateManifest manifest, string current)
    {
        Validate(manifest);
        if (CompareVersions(current, manifest.minimum_version) < 0)
            throw new InvalidDataException("먼저 LAKIS " + manifest.minimum_version + " 중간 업데이트를 설치해 주세요.");
        if (CompareVersions(manifest.version, current) < 0)
            throw new InvalidDataException("현재 설치보다 이전 버전으로 업데이트할 수 없습니다.");
        if (manifest.kind == "file-patch" && CompareVersions(manifest.version, current) > 0 &&
            manifest.files.Count == 0 && manifest.delete.Count == 0)
            throw new InvalidDataException("파일 변경이 없는 명세로 설치 버전을 올릴 수 없습니다.");
    }

    internal static void ValidateRuntimeContinuation(UpdateManifest manifest, string current)
    {
        if (CompareVersions(current, RuntimeBridgeVersion) != 0 ||
            manifest.kind != "runtime-update" ||
            CompareVersions(manifest.version, EngineVersion) < 0 ||
            CompareVersions(manifest.minimum_updater_version, EngineVersion) < 0)
            throw new InvalidDataException("중간 업데이터 다음 단계에는 검증된 8.0 런타임 업데이트가 필요합니다.");
    }

    internal static void EnsureNoPendingRuntimeTransition(string root)
    {
        root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
        string journal = Path.Combine(Path.GetDirectoryName(root),
            "." + Path.GetFileName(root) + "-runtime-transition.json");
        if (!File.Exists(journal)) return;
        try
        {
            if ((File.GetAttributes(journal) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("업데이트 상태 파일이 링크입니다.");
            string json;
            using (var stream = new FileStream(journal, FileMode.Open, FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(stream)) json = reader.ReadToEnd();
            var state = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(json);
            object target, phase, schema;
            if (state == null || !state.TryGetValue("target", out target) ||
                !state.TryGetValue("phase", out phase) || !state.TryGetValue("schema", out schema) ||
                !(schema is int) || ((int)schema != 1 && (int)schema != 2) ||
                !(target is string) || !String.Equals(Path.GetFullPath((string)target).TrimEnd(Path.DirectorySeparatorChar),
                    root, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("업데이트 상태 정보가 설치 경로와 일치하지 않습니다.");
            if ((string)phase != "complete" && (string)phase != "rolled-back")
                throw new InvalidDataException("진행 중이거나 중단된 런타임 업데이트가 있습니다. 복구를 마친 뒤 실행해 주세요.");
        }
        catch (InvalidDataException) { throw; }
        catch (Exception error)
        {
            throw new InvalidDataException("업데이트 상태를 확인할 수 없어 실행을 중단합니다. 상태 파일: " + journal, error);
        }
    }
}
