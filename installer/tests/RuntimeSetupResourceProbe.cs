using System;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;

internal static class RuntimeSetupResourceProbe
{
    private static string Hash(Stream stream)
    {
        using(var sha=SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","");
    }

    private static string HashFile(string path)
    {
        using(var stream=File.OpenRead(path))return Hash(stream);
    }

    private static int Main(string[] args)
    {
        try
        {
            var assembly=Assembly.LoadFile(Path.GetFullPath(args[0]));
            var flags=BindingFlags.NonPublic|BindingFlags.Static;
            var setup=assembly.GetType("SafeInstaller",true);
            string manifest=(string)setup.GetMethod("ReadRuntimeInstallManifest",flags).Invoke(null,null);
            if(manifest!=File.ReadAllText(args[1]))return 10;
            using(var embedded=assembly.GetManifestResourceStream("LAKIS.RuntimeInstallManifest"))
                if(embedded==null||Hash(embedded)!=HashFile(args[1]))return 11;
            using(var embedded=assembly.GetManifestResourceStream("LAKIS.7zr"))
                if(embedded==null||Hash(embedded)!="AD4C82FADCBDF93C03B4FC440F300509C7D60C5C2F4D183E35D9D70D6957037D")return 12;
            var engine=assembly.GetType("RuntimeBundleInstaller",true);
            string workspace=(string)engine.GetMethod("CreateWorkspace",flags).Invoke(null,null);
            engine.GetMethod("VerifyHelpers",flags).Invoke(null,new object[]{workspace});
            string[] helpers=(string[])engine.GetField("Helpers",flags).GetValue(null);
            foreach(string name in helpers)
                if(HashFile(Path.Combine(workspace,name))!=HashFile(Path.Combine(args[2],name)))return 13;
            Console.WriteLine("PRIVATE_SETUP_REAL_ENGINE_RESOURCE_PASS");
            Console.WriteLine("HELPERS="+helpers.Length);
            Console.WriteLine("WORKSPACE="+workspace);
            return 0;
        }
        catch(Exception error){Console.Error.WriteLine(error);return 1;}
    }
}
