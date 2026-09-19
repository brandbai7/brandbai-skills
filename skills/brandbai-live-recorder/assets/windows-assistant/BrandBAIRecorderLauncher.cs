using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;

[assembly: AssemblyTitle("BrandBAI 直播采集助手")]
[assembly: AssemblyDescription("启动 BrandBAI 本机直播录屏服务")]
[assembly: AssemblyCompany("BrandBAI")]
[assembly: AssemblyProduct("BrandBAI 直播采集助手")]
[assembly: AssemblyCopyright("Copyright BrandBAI")]
[assembly: AssemblyVersion("0.22.16.0")]
[assembly: AssemblyFileVersion("0.22.16.0")]

internal static class Program
{
    private const string AllowedRequest = "brandbai-recorder://start";
    private const string ConfigFileName = "launcher.cfg";

    [STAThread]
    public static int Main(string[] args)
    {
        try
        {
            if (args.Length != 1 || !IsAllowedRequest(args[0]))
            {
                return 2;
            }

            string executablePath = Assembly.GetExecutingAssembly().Location;
            string applicationDirectory = Path.GetDirectoryName(executablePath);
            if (String.IsNullOrWhiteSpace(applicationDirectory))
            {
                return 2;
            }

            string configPath = Path.Combine(applicationDirectory, ConfigFileName);
            if (!File.Exists(configPath))
            {
                return 2;
            }

            string[] config = File.ReadAllLines(configPath, Encoding.UTF8);
            if (config.Length != 2)
            {
                return 2;
            }

            string pythonWindowed = Path.GetFullPath(config[0]);
            string assistantScript = Path.GetFullPath(config[1]);
            if (!File.Exists(pythonWindowed) || !File.Exists(assistantScript))
            {
                return 2;
            }

            ProcessStartInfo startInfo = new ProcessStartInfo
            {
                FileName = pythonWindowed,
                Arguments = "-B " + Quote(assistantScript) + " start --quiet " + Quote(AllowedRequest),
                WorkingDirectory = Path.GetDirectoryName(assistantScript),
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            Process.Start(startInfo);
            return 0;
        }
        catch
        {
            return 2;
        }
    }

    private static bool IsAllowedRequest(string request)
    {
        string normalized = (request ?? String.Empty).Trim();
        if (normalized.EndsWith("/", StringComparison.Ordinal))
        {
            normalized = normalized.Substring(0, normalized.Length - 1);
        }
        return String.Equals(normalized, AllowedRequest, StringComparison.OrdinalIgnoreCase);
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
