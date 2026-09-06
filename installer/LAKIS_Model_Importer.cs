using System;
using System.Drawing;
using System.IO;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class LakisModelImporter
{
    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string root = args.Length > 0 ? args[0] : AppDomain.CurrentDomain.BaseDirectory;
        Application.Run(new ImportForm(root));
    }

    private sealed class ImportForm : Form
    {
        private readonly TextBox source = new TextBox();
        private readonly Label licence = new Label();
        private readonly Label destination = new Label();
        private readonly Label status = new Label();
        private readonly CheckBox confirmRestricted = new CheckBox();
        private readonly CheckBox removeSource = new CheckBox();
        private readonly Button import = new Button();
        private string installRoot;

        internal ImportForm(string root)
        {
            installRoot = ResolveRoot(root);
            Text = "LAKIS 모델 가져오기";
            ClientSize = new Size(620, 455);
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(12, 14, 22);
            ForeColor = Color.FromArgb(225, 229, 255);
            Font = new Font("Segoe UI", 10F);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            AllowDrop = true;

            var title = MakeLabel(30, 24, 555, 36, "LAKIS 모델 가져오기", 19F, true, Color.FromArgb(152, 112, 255));
            var intro = MakeLabel(32, 65, 550, 43,
                "사용자가 직접 다운로드한 업스케일 모델을 안전하게 LAKIS에 가져옵니다.\n파일을 아래 칸에 드래그해도 됩니다.", 9.5F, false, Color.FromArgb(171, 178, 203));
            var sourceTitle = MakeLabel(32, 121, 130, 23, "다운로드한 파일", 9.5F, true, ForeColor);
            source.SetBounds(32, 148, 450, 34);
            source.ReadOnly = true;
            source.BackColor = Color.FromArgb(9, 11, 18);
            source.ForeColor = ForeColor;
            source.BorderStyle = BorderStyle.FixedSingle;
            var choose = MakeButton(493, 147, 94, 36, "파일 선택");
            choose.Click += delegate { ChooseFile(); };

            licence.SetBounds(32, 200, 555, 55);
            licence.ForeColor = Color.FromArgb(171, 178, 203);
            licence.Text = "파일을 선택하면 알려진 이용 조건을 표시합니다.";
            confirmRestricted.SetBounds(32, 257, 555, 30);
            confirmRestricted.Text = "비상업용 모델의 이용 조건을 확인했습니다.";
            confirmRestricted.ForeColor = Color.FromArgb(255, 166, 201);
            confirmRestricted.Visible = false;
            removeSource.SetBounds(32, 289, 555, 27);
            removeSource.Text = "가져온 후 원본 파일 삭제(복사가 아닌 이동)";
            removeSource.ForeColor = Color.FromArgb(171, 178, 203);

            destination.SetBounds(32, 326, 555, 38);
            destination.ForeColor = Color.FromArgb(124, 211, 255);
            destination.Text = "대상: " + TargetDirectory();
            status.SetBounds(32, 371, 390, 48);
            status.ForeColor = Color.FromArgb(171, 178, 203);
            status.Text = "파일은 .pth, .pt, .safetensors 형식만 받습니다.";
            import.SetBounds(442, 374, 145, 48);
            import.Text = "가져오기";
            import.Enabled = false;
            import.FlatStyle = FlatStyle.Flat;
            import.FlatAppearance.BorderSize = 0;
            import.BackColor = Color.FromArgb(103, 80, 220);
            import.ForeColor = Color.White;
            import.Font = new Font("Segoe UI", 11F, FontStyle.Bold);
            import.Click += async delegate { await ImportAsync(); };

            Controls.AddRange(new Control[] { title, intro, sourceTitle, source, choose, licence,
                confirmRestricted, removeSource, destination, status, import });
            DragEnter += OnDragEnter;
            DragDrop += OnDragDrop;
        }

        private static Label MakeLabel(int x, int y, int w, int h, string text, float size, bool bold, Color color)
        {
            return new Label { Left=x, Top=y, Width=w, Height=h, Text=text, ForeColor=color,
                Font=new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular) };
        }

        private static Button MakeButton(int x, int y, int w, int h, string text)
        {
            var button = new Button { Left=x, Top=y, Width=w, Height=h, Text=text,
                FlatStyle=FlatStyle.Flat, ForeColor=Color.FromArgb(220, 225, 240),
                BackColor=Color.FromArgb(24, 28, 40), Cursor=Cursors.Hand };
            button.FlatAppearance.BorderColor = Color.FromArgb(55, 64, 88);
            return button;
        }

        private static string ResolveRoot(string candidate)
        {
            string full;
            try { full = Path.GetFullPath(candidate.Trim('"')); }
            catch { full = AppDomain.CurrentDomain.BaseDirectory; }
            if (Directory.Exists(Path.Combine(full, "ComfyUI"))) return full;
            DirectoryInfo cursor = new DirectoryInfo(full);
            for (int i=0; i<6 && cursor!=null; i++, cursor=cursor.Parent)
                if (Directory.Exists(Path.Combine(cursor.FullName, "ComfyUI"))) return cursor.FullName;
            return full;
        }

        private string TargetDirectory()
        {
            return Path.Combine(installRoot, "ComfyUI", "models", "upscale_models");
        }

        private void ChooseFile()
        {
            using (var dialog = new OpenFileDialog())
            {
                dialog.Title = "업스케일 모델 선택";
                dialog.Filter = "Upscale models|*.pth;*.pt;*.safetensors";
                if (dialog.ShowDialog(this) == DialogResult.OK) SelectFile(dialog.FileName);
            }
        }

        private void OnDragEnter(object sender, DragEventArgs e)
        {
            if (e.Data.GetDataPresent(DataFormats.FileDrop)) e.Effect = DragDropEffects.Copy;
        }

        private void OnDragDrop(object sender, DragEventArgs e)
        {
            string[] files = e.Data.GetData(DataFormats.FileDrop) as string[];
            if (files != null && files.Length == 1) SelectFile(files[0]);
            else MessageBox.Show(this, "모델 파일 하나만 가져올 수 있습니다.", Text,
                MessageBoxButtons.OK, MessageBoxIcon.Information);
        }

        private static bool IsAccepted(string path)
        {
            string ext = Path.GetExtension(path).ToLowerInvariant();
            return ext == ".pth" || ext == ".pt" || ext == ".safetensors";
        }

        private void SelectFile(string path)
        {
            if (!File.Exists(path) || !IsAccepted(path))
            {
                MessageBox.Show(this, "지원하지 않는 파일입니다.\n.pth, .pt, .safetensors만 선택해 주세요.", Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            source.Text = Path.GetFullPath(path);
            string name = Path.GetFileName(path);
            bool animeSharp = name.IndexOf("AnimeSharp", StringComparison.OrdinalIgnoreCase) >= 0;
            bool realEsrganAnime = name.IndexOf("RealESRGAN_x4plus_anime_6B", StringComparison.OrdinalIgnoreCase) >= 0;
            confirmRestricted.Visible = animeSharp;
            confirmRestricted.Checked = false;
            if (animeSharp)
            {
                licence.Text = "비상업용 · CC BY-NC-SA 4.0\n상업적 이용은 허용되지 않으며, 출처 표시와 동일조건변경허락 조건이 적용됩니다.";
                licence.ForeColor = Color.FromArgb(255, 130, 180);
            }
            else if (realEsrganAnime)
            {
                licence.Text = "BSD-3-Clause · 상업적 이용 가능\nReal-ESRGAN 공식 애니메이션 특화 모델입니다.";
                licence.ForeColor = Color.FromArgb(102, 232, 177);
            }
            else
            {
                licence.Text = "이용 조건 자동 확인 불가\n해당 파일의 배포 페이지에서 라이선스와 상업적 이용 가능 여부를 확인해 주세요.";
                licence.ForeColor = Color.FromArgb(255, 196, 112);
            }
            import.Enabled = true;
            status.Text = new FileInfo(path).Length == 0 ? "빈 파일은 가져올 수 없습니다." : "가져오기 준비 완료";
        }

        private async Task ImportAsync()
        {
            string input = source.Text;
            if (!File.Exists(input) || !IsAccepted(input)) return;
            if (new FileInfo(input).Length == 0)
            {
                MessageBox.Show(this, "빈 파일은 가져올 수 없습니다.", Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Warning); return;
            }
            bool restricted = Path.GetFileName(input).IndexOf("AnimeSharp", StringComparison.OrdinalIgnoreCase) >= 0;
            if (restricted && !confirmRestricted.Checked)
            {
                MessageBox.Show(this, "비상업용 이용 조건을 먼저 확인해 주세요.", Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Warning); return;
            }
            string directory = TargetDirectory();
            string output = Path.Combine(directory, Path.GetFileName(input));
            if (String.Equals(Path.GetFullPath(input), Path.GetFullPath(output), StringComparison.OrdinalIgnoreCase))
            {
                MessageBox.Show(this, "이미 올바른 LAKIS 폴더에 있는 파일입니다.", Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Information); return;
            }
            if (File.Exists(output) && MessageBox.Show(this, "동일한 이름의 모델이 있습니다. 교체할까요?", Text,
                MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;

            import.Enabled = false;
            status.Text = "파일 검증 및 가져오기 중…";
            try
            {
                string hash = await Task.Run(delegate { return CopyVerified(input, output); });
                if (removeSource.Checked) File.Delete(input);
                status.Text = "완료 · SHA-256 " + hash.Substring(0, 16) + "…";
                MessageBox.Show(this, "모델을 LAKIS에 가져왔습니다.\n\n" + output +
                    "\n\nComfyUI가 실행 중이면 모델 목록을 새로고침해 주세요.", Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch (Exception error)
            {
                status.Text = "가져오기 실패";
                MessageBox.Show(this, "모델을 가져오지 못했습니다.\n\n" + error.Message, Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally { import.Enabled = true; }
        }

        private static string CopyVerified(string input, string output)
        {
            string directory = Path.GetDirectoryName(output);
            Directory.CreateDirectory(directory);
            string temporary = Path.Combine(directory, ".lakis-import-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                using (var sourceStream = new FileStream(input, FileMode.Open, FileAccess.Read, FileShare.Read))
                using (var outputStream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    sourceStream.CopyTo(outputStream, 1024 * 1024);
                if (new FileInfo(input).Length != new FileInfo(temporary).Length)
                    throw new IOException("복사된 파일 크기가 원본과 다릅니다.");
                string inputHash = Hash(input);
                string outputHash = Hash(temporary);
                if (!String.Equals(inputHash, outputHash, StringComparison.OrdinalIgnoreCase))
                    throw new IOException("SHA-256 검증에 실패했습니다.");
                if (File.Exists(output)) File.Replace(temporary, output, null);
                else File.Move(temporary, output);
                return outputHash;
            }
            finally { try { if (File.Exists(temporary)) File.Delete(temporary); } catch { } }
        }

        private static string Hash(string path)
        {
            using (var stream = File.OpenRead(path))
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "");
        }
    }
}
