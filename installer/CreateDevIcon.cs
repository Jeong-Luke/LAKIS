using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;

internal static class CreateDevIcon
{
    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Length != 2) throw new ArgumentException("source.ico output.ico");
        using (var source = new Icon(args[0], new Size(256, 256)))
        using (var input = source.ToBitmap())
        using (var output = new Bitmap(256, 256, PixelFormat.Format32bppArgb))
        {
            using (var graphics = Graphics.FromImage(output))
            {
                graphics.Clear(Color.Transparent);
                graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
                graphics.DrawImage(input, new Rectangle(0, 0, 256, 256));
            }
            for (int y = 0; y < output.Height; y++)
            for (int x = 0; x < output.Width; x++)
            {
                Color c = output.GetPixel(x, y);
                if (c.A == 0) continue;
                int luminance = (c.R * 30 + c.G * 59 + c.B * 11) / 100;
                int red = Math.Min(255, 72 + luminance);
                int green = Math.Min(96, luminance / 3);
                int blue = Math.Min(112, luminance / 3 + 12);
                output.SetPixel(x, y, Color.FromArgb(c.A, red, green, blue));
            }
            using (var png = new MemoryStream())
            {
                output.Save(png, ImageFormat.Png);
                byte[] image = png.ToArray();
                File.WriteAllBytes(Path.ChangeExtension(args[1], ".png"), image);
                using (var file = new BinaryWriter(File.Create(args[1])))
                {
                    file.Write((ushort)0); file.Write((ushort)1); file.Write((ushort)1);
                    file.Write((byte)0); file.Write((byte)0); file.Write((byte)0); file.Write((byte)0);
                    file.Write((ushort)1); file.Write((ushort)32);
                    file.Write((uint)image.Length); file.Write((uint)22); file.Write(image);
                }
            }
        }
    }
}
