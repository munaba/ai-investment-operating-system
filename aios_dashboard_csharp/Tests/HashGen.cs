
using BCrypt.Net;
using System;
class HashGen { static void Main() { Console.WriteLine(BCrypt.Net.BCrypt.HashPassword("password123", 11)); } }
