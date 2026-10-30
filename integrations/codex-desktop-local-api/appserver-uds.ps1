$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$socketPath = Join-Path $env:CODEX_HOME 'app-server-control\app-server-control.sock'

$source = @'
using System;
using System.IO;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

public static class CodexUdsWebSocketBridge
{
    static Stream stream;
    static readonly object writeLock = new object();
    static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);

    static byte[] ReadExact(int count)
    {
        var bytes = new byte[count]; int offset = 0;
        while (offset < count) { int n = stream.Read(bytes, offset, count - offset); if (n == 0) throw new EndOfStreamException(); offset += n; }
        return bytes;
    }

    static void SendFrame(byte opcode, byte[] payload)
    {
        lock (writeLock)
        {
            using (var output = new MemoryStream())
            {
                output.WriteByte((byte)(0x80 | opcode));
                if (payload.Length < 126) output.WriteByte((byte)(0x80 | payload.Length));
                else if (payload.Length <= 65535) { output.WriteByte(0xFE); output.WriteByte((byte)(payload.Length >> 8)); output.WriteByte((byte)payload.Length); }
                else { output.WriteByte(0xFF); var len = BitConverter.GetBytes((ulong)payload.Length); if (BitConverter.IsLittleEndian) Array.Reverse(len); output.Write(len, 0, len.Length); }
                var mask = new byte[4]; RandomNumberGenerator.Fill(mask); output.Write(mask, 0, 4);
                var encoded = new byte[payload.Length]; for (int i = 0; i < payload.Length; i++) encoded[i] = (byte)(payload[i] ^ mask[i & 3]);
                output.Write(encoded, 0, encoded.Length); var frame = output.ToArray(); stream.Write(frame, 0, frame.Length); stream.Flush();
            }
        }
    }

    static void SendText(string text) => SendFrame(1, Utf8.GetBytes(text));

    static string ReadFrame()
    {
        while (true)
        {
            var head = ReadExact(2); byte opcode = (byte)(head[0] & 0x0F); bool masked = (head[1] & 0x80) != 0; ulong length = (ulong)(head[1] & 0x7F);
            if (length == 126) { var b = ReadExact(2); length = (ulong)((b[0] << 8) | b[1]); }
            else if (length == 127) { var b = ReadExact(8); length = 0; foreach (byte v in b) length = (length << 8) | v; }
            if (length > 33554432) throw new InvalidDataException("WebSocket frame exceeds 32 MiB");
            var mask = masked ? ReadExact(4) : null; var payload = ReadExact((int)length);
            if (masked) for (int i = 0; i < payload.Length; i++) payload[i] ^= mask[i & 3];
            if (opcode == 8) return null;
            if (opcode == 9) { SendFrame(10, payload); continue; }
            if (opcode == 10) continue;
            if (opcode == 1 || opcode == 2) return Utf8.GetString(payload);
            // The current App Server emits complete, unfragmented JSON text frames.
        }
    }

    static void Handshake(string path)
    {
        var socket = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
        socket.Connect(new UnixDomainSocketEndPoint(path)); stream = new NetworkStream(socket, true);
        var keyBytes = new byte[16]; RandomNumberGenerator.Fill(keyBytes); string key = Convert.ToBase64String(keyBytes);
        string request = "GET /rpc HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " + key + "\r\nSec-WebSocket-Version: 13\r\n\r\n";
        var bytes = Encoding.ASCII.GetBytes(request); stream.Write(bytes, 0, bytes.Length); stream.Flush();
        var header = new MemoryStream(); int matched = 0; byte[] end = new byte[] { 13, 10, 13, 10 };
        while (matched < 4) { int b = stream.ReadByte(); if (b < 0) throw new EndOfStreamException("WebSocket handshake ended early"); header.WriteByte((byte)b); matched = (byte)b == end[matched] ? matched + 1 : ((byte)b == 13 ? 1 : 0); if (header.Length > 16384) throw new InvalidDataException("WebSocket response headers too large"); }
        string response = Encoding.ASCII.GetString(header.ToArray());
        if (!response.StartsWith("HTTP/1.1 101", StringComparison.Ordinal)) throw new InvalidDataException("WebSocket upgrade rejected: " + response.Split('\n')[0]);
        string accept = Convert.ToBase64String(SHA1.HashData(Encoding.ASCII.GetBytes(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")));
        if (!response.Contains("Sec-WebSocket-Accept: " + accept, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Invalid Sec-WebSocket-Accept response");
    }

    public static int Run(string path)
    {
        try { Handshake(path); }
        catch (Exception ex) { Console.Error.WriteLine("App Server socket connect failed: " + ex.Message); return 2; }
        using (var cancelled = new CancellationTokenSource())
        {
            var reader = Task.Run(() => {
                try { while (!cancelled.IsCancellationRequested) { var message = ReadFrame(); if (message == null) break; Console.Out.WriteLine(message); Console.Out.Flush(); } }
                catch (Exception ex) { if (!cancelled.IsCancellationRequested) Console.Error.WriteLine("App Server socket read failed: " + ex.Message); }
                finally { cancelled.Cancel(); }
            });
            try
            {
                string line;
                while (!cancelled.IsCancellationRequested && (line = Console.ReadLine()) != null) SendText(line);
            }
            catch (Exception ex) { Console.Error.WriteLine("App Server socket write failed: " + ex.Message); }
            finally { cancelled.Cancel(); try { SendFrame(8, new byte[0]); } catch { } try { stream.Dispose(); } catch { } }
            try { reader.Wait(1000); } catch { }
        }
        return 0;
    }
}
'@

Add-Type -TypeDefinition $source -Language CSharp
exit [CodexUdsWebSocketBridge]::Run($socketPath)
