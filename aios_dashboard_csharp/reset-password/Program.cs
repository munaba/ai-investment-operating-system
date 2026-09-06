// Tool regenerate password hash dashboard AIOS.
// Pakai (dari folder project):  dotnet run --project reset-password
// Password diketik hidden, tidak pernah muncul di history/shell.
// Hasil: baris "PasswordHash" untuk ditempel ke appsettings.json, lalu restart server.

using System.Security;

Console.Write("Password baru (input hidden, min 10 karakter): ");
var pwd = ReadPassword();
if (string.IsNullOrWhiteSpace(pwd) || pwd.Length < 10)
{
    Console.WriteLine();
    Console.WriteLine("ERROR: password kosong atau terlalu pendek (min 10 karakter).");
    return 1;
}

var hash = BCrypt.Net.BCrypt.HashPassword(pwd, workFactor: 11);
Console.WriteLine();
Console.WriteLine("Tempel baris ini ke appsettings.json (ganti nilai PasswordHash lama):");
Console.WriteLine();
Console.WriteLine($"\"PasswordHash\": \"{hash}\",");
Console.WriteLine();
Console.WriteLine("Lalu restart server (stop proses dotnet, jalankan ulang).");
return 0;

static string ReadPassword()
{
    var result = new System.Text.StringBuilder();
    while (true)
    {
        var key = Console.ReadKey(intercept: true);
        if (key.Key == ConsoleKey.Enter) break;
        if (key.Key == ConsoleKey.Backspace)
        {
            if (result.Length > 0) result.Length--;
        }
        else if (!char.IsControl(key.KeyChar))
        {
            result.Append(key.KeyChar);
        }
    }
    return result.ToString();
}
