using System;
using System.Diagnostics;
using System.IO.Ports;
using System.Text;
using System.Threading;

namespace FanCycle {
    public interface IWire : IDisposable {
        int ReadByte();
        void Write(string text);
        bool IsOpen { get; }
    }
    public sealed class SerialWire : IWire {
        readonly SerialPort port;
        public SerialWire(string name) {
            port = new SerialPort(name,115200,Parity.None,8,StopBits.One);
            port.ReadTimeout=50; port.WriteTimeout=1000; port.NewLine="\n";
            try {
                port.DtrEnable=false; port.Open(); Thread.Sleep(150);
                port.DiscardInBuffer(); port.DtrEnable=true;
            } catch { port.Dispose(); throw; }
        }
        public int ReadByte() { return port.ReadByte(); }
        public void Write(string text) { port.Write(text); }
        public bool IsOpen { get { return port.IsOpen; } }
        public void Dispose() { port.Dispose(); }
    }
    public sealed class FanSession : IDisposable {
        readonly IWire wire;
        public bool Identified { get; private set; }
        public FanSession(IWire transport) { wire=transport; }
        string ReadFrame(Stopwatch clock,int limit) {
            var text=new StringBuilder();
            while(clock.ElapsedMilliseconds<limit) {
                int b;
                try { b=wire.ReadByte(); } catch(TimeoutException) { continue; }
                if(clock.ElapsedMilliseconds>=limit) throw new TimeoutException("Serial deadline exceeded; late frame rejected.");
                if(b==10) return text.ToString().TrimEnd('\r');
                if(b<0 || b>127) throw new InvalidOperationException("Non-ASCII serial frame.");
                text.Append((char)b);
                if(text.Length>64) throw new InvalidOperationException("Serial frame exceeds 64 bytes.");
            }
            throw new TimeoutException("Serial deadline exceeded; physical fan state unknown.");
        }
        public void Identify(int timeoutMs) {
            var clock=Stopwatch.StartNew();
            for(int frames=0; frames<64 && clock.ElapsedMilliseconds<timeoutMs; frames++) {
                string line=ReadFrame(clock,timeoutMs);
                if(line=="READY UNO_FAN_V2 25000") { Identified=true; return; }
            }
            throw new InvalidOperationException("Exact UNO_FAN_V2 identity not received; no commands sent.");
        }
        public string Command(string command,int timeoutMs) {
            if(!Identified) throw new InvalidOperationException("Board identity required before writing.");
            int expected=-1;
            if(command!="STATUS") {
                if(!command.StartsWith("SET ",StringComparison.Ordinal) ||
                   !Int32.TryParse(command.Substring(4),out expected) || expected<0 || expected>100 ||
                   command!="SET "+expected.ToString(System.Globalization.CultureInfo.InvariantCulture))
                    throw new ArgumentException("Only STATUS or SET integer 0..100 permitted.");
            }
            var clock=Stopwatch.StartNew(); wire.Write(command+"\n");
            for(int frames=0;frames<32 && clock.ElapsedMilliseconds<timeoutMs;frames++) {
                string reply=ReadFrame(clock,timeoutMs);
                if(reply.StartsWith("ERR ",StringComparison.Ordinal)) throw new InvalidOperationException(reply);
                if(!reply.StartsWith("OK DUTY ",StringComparison.Ordinal)) continue;
                int actual;
                if(!Int32.TryParse(reply.Substring(8),out actual) || actual<0 || actual>100 ||
                   reply!="OK DUTY "+actual.ToString(System.Globalization.CultureInfo.InvariantCulture))
                    throw new InvalidOperationException("Malformed duty acknowledgement.");
                if(expected>=0 && actual!=expected) throw new InvalidOperationException("Duty acknowledgement mismatch: "+reply);
                return reply;
            }
            throw new TimeoutException("No valid acknowledgement; physical fan state unknown.");
        }
        public void Dispose() { wire.Dispose(); }
    }
    public static class CancelSignal {
        public static volatile bool Requested;
        static ConsoleCancelEventHandler handler;
        public static void Install() {
            Requested=false;
            handler=delegate(object sender,ConsoleCancelEventArgs e) { e.Cancel=true; Requested=true; };
            Console.CancelKeyPress+=handler;
        }
        public static void Remove() { if(handler!=null) Console.CancelKeyPress-=handler; handler=null; }
    }
}
