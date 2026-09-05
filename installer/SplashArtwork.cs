using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal static class LakisWindowDrag
{
    private const int WM_NCLBUTTONDOWN = 0xA1;
    private const int HTCAPTION = 0x2;
    [DllImport("user32.dll")] private static extern bool ReleaseCapture();
    [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr handle, int message, int wParam, int lParam);

    internal static void Enable(Form form)
    {
        form.MouseDown += (_, eventArgs) => {
            if (eventArgs.Button != MouseButtons.Left || eventArgs.Y > 46) return;
            ReleaseCapture();
            SendMessage(form.Handle, WM_NCLBUTTONDOWN, HTCAPTION, 0);
        };
    }
}

internal sealed class CenterCropPictureBox : PictureBox
{
    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.Clear(BackColor);
        if (Image == null) return;
        e.Graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
        e.Graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
        double scale = Math.Max((double)ClientSize.Width / Image.Width,
                                (double)ClientSize.Height / Image.Height);
        int width = (int)Math.Ceiling(Image.Width * scale);
        int height = (int)Math.Ceiling(Image.Height * scale);
        int x = (ClientSize.Width - width) / 2;
        int y = (ClientSize.Height - height) / 2;
        e.Graphics.DrawImage(Image, new Rectangle(x, y, width, height));
    }
}

internal sealed class LakisProgressBar : Control
{
    private readonly Timer animationTimer = new Timer();
    private int animationOffset;
    private int minimum;
    private int maximum = 100;
    private int currentValue;
    private ProgressBarStyle progressStyle;

    internal LakisProgressBar()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.ResizeRedraw | ControlStyles.UserPaint, true);
        BackColor = Color.FromArgb(29, 35, 50);
        animationTimer.Interval = 22;
        animationTimer.Tick += (_, __) => {
            animationOffset = (animationOffset + 5) % Math.Max(1, Width + 90);
            Invalidate();
        };
    }

    public int Minimum { get { return minimum; } set { minimum = value; Invalidate(); } }
    public int Maximum { get { return maximum; } set { maximum = Math.Max(value, minimum + 1); Invalidate(); } }
    public int Value {
        get { return currentValue; }
        set { currentValue = Math.Max(minimum, Math.Min(maximum, value)); Invalidate(); }
    }
    public int MarqueeAnimationSpeed {
        get { return animationTimer.Interval; }
        set { animationTimer.Interval = Math.Max(10, value); }
    }
    public ProgressBarStyle Style {
        get { return progressStyle; }
        set {
            progressStyle = value;
            if (value == ProgressBarStyle.Marquee) animationTimer.Start(); else animationTimer.Stop();
            Invalidate();
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using (var track = new SolidBrush(BackColor)) e.Graphics.FillRectangle(track, ClientRectangle);
        Rectangle fill;
        if (Style == ProgressBarStyle.Marquee)
        {
            int segment = Math.Max(60, Width / 3);
            int x = animationOffset - segment;
            fill = new Rectangle(x, 0, segment, Height);
        }
        else
        {
            double ratio = (double)(Value - Minimum) / Math.Max(1, Maximum - Minimum);
            fill = new Rectangle(0, 0, (int)Math.Round(Width * ratio), Height);
        }
        if (fill.Width > 0)
            using (var gradient = new LinearGradientBrush(fill,
                Color.FromArgb(116, 77, 255), Color.FromArgb(62, 139, 255), 0F))
                e.Graphics.FillRectangle(gradient, fill);
        using (var border = new Pen(Color.FromArgb(55, 65, 91)))
            e.Graphics.DrawRectangle(border, 0, 0, Math.Max(0, Width - 1), Math.Max(0, Height - 1));
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) animationTimer.Dispose();
        base.Dispose(disposing);
    }
}
