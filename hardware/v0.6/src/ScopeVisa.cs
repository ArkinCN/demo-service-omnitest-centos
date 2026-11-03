using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace FanCycle {
    public sealed class ScopeVisa : IDisposable {
        [DllImport("visa64.dll")] static extern int viOpenDefaultRM(out int session);
        [DllImport("visa64.dll")] static extern int viOpen(int rm,string resource,int mode,int timeout,out int session);
        [DllImport("visa64.dll")] static extern int viSetAttribute(int session,int attribute,int value);
        [DllImport("visa64.dll")] static extern int viWrite(int session,byte[] bytes,int count,out int written);
        [DllImport("visa64.dll")] static extern int viRead(int session,byte[] bytes,int count,out int read);
        [DllImport("visa64.dll")] static extern int viClose(int session);
        int rm,session;
        const int SuccessMaxCount=0x3fff0006;
        static void Check(int status,string operation) {
            if(status<0) throw new IOException(operation+" VISA error 0x"+unchecked((uint)status).ToString("X8"));
        }
        public ScopeVisa(string resource) {
            if(!Environment.Is64BitProcess) throw new InvalidOperationException("64-bit PowerShell required for visa64.dll.");
            try {
                Check(viOpenDefaultRM(out rm),"Open resource manager");
                Check(viOpen(rm,resource,0,3000,out session),"Open scope");
                Check(viSetAttribute(session,unchecked((int)0x3fff001a),3000),"Set timeout");
            } catch { Dispose(); throw; }
        }
        public void Write(string command) {
            Check(viSetAttribute(session,unchecked((int)0x3fff001a),3000),"Set write timeout");
            byte[] bytes=Encoding.ASCII.GetBytes(command+"\n"); int written;
            Check(viWrite(session,bytes,bytes.Length,out written),"Write "+command);
            if(written!=bytes.Length) throw new IOException("Incomplete VISA write.");
        }
        public byte[] QueryBytes(string command) {
            var clock=Stopwatch.StartNew();
            Write(command);
            using(var stream=new MemoryStream()) {
                for(int calls=0;calls<64 && clock.ElapsedMilliseconds<6000;calls++) {
                    byte[] buffer=new byte[65536]; int count;
                    int remaining=6000-(int)clock.ElapsedMilliseconds;
                    if(remaining<=0) throw new TimeoutException("VISA response deadline exceeded.");
                    Check(viSetAttribute(session,unchecked((int)0x3fff001a),Math.Min(3000,remaining)),"Set bounded read timeout");
                    int status=viRead(session,buffer,buffer.Length,out count); Check(status,"Read "+command);
                    if(clock.ElapsedMilliseconds>=6000) throw new TimeoutException("VISA response deadline exceeded.");
                    if(count<=0 || count>buffer.Length) throw new IOException("Invalid VISA read count.");
                    stream.Write(buffer,0,count);
                    if(stream.Length>2097152) throw new IOException("VISA response exceeds 2 MiB.");
                    if(status!=SuccessMaxCount) return stream.ToArray();
                }
                throw new TimeoutException("VISA response deadline exceeded.");
            }
        }
        public string Query(string command) { return Encoding.ASCII.GetString(QueryBytes(command)).Trim(); }
        public static byte[] BlockPayload(byte[] bytes) {
            if(bytes.Length<3 || bytes[0]!='#' || bytes[1]<'1' || bytes[1]>'9')
                throw new IOException("Expected a definite SCPI block.");
            int digits=bytes[1]-'0';
            if(bytes.Length<2+digits) throw new IOException("Truncated SCPI length.");
            int length;
            if(!Int32.TryParse(Encoding.ASCII.GetString(bytes,2,digits),out length) || length<0 || length>2097152)
                throw new IOException("Invalid SCPI length.");
            if(bytes.Length<2+digits+length) throw new IOException("Truncated SCPI payload.");
            for(int i=2+digits+length;i<bytes.Length;i++)
                if(bytes[i]!=10 && bytes[i]!=13) throw new IOException("Unexpected SCPI trailing bytes.");
            byte[] payload=new byte[length]; Buffer.BlockCopy(bytes,2+digits,payload,0,length); return payload;
        }
        public void Dispose() {
            if(session!=0) { viClose(session); session=0; }
            if(rm!=0) { viClose(rm); rm=0; }
        }
    }
}
