using BCrypt.Net;

class Program
{
    static void Main()
    {
        var hash = BCrypt.Net.BCrypt.HashPassword("password123", 11);
        Console.WriteLine(hash);
    }
}