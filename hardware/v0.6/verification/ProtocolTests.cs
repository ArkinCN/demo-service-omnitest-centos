using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Threading;
using FanCycle;

public sealed class FakeWire : IWire {
    readonly Queue<int> bytes=new Queue<int>();
    public readonly List<string> Writes=new List<string>();
    public bool IsOpen { get { return true; } }
    public bool AutoAck;
    public bool CleanupFails;
    public int Duty;
    public void Feed(string text) { foreach(char c in text) bytes.Enqueue(c); }
    public int ReadByte() {
        if(bytes.Count>0) return bytes.Dequeue();
        Thread.Sleep(1); throw new TimeoutException();
    }
    public void Write(string text) {
        Writes.Add(text);
        if(AutoAck) {
            if(text=="SET 0\n" && CleanupFails) Feed("ERR COMMAND\n");
            else if(text.StartsWith("SET ")) { Duty=Int32.Parse(text.Substring(4).Trim()); Feed("OK DUTY "+Duty+"\n"); }
            else Feed("OK DUTY "+Duty+"\n");
        }
    }
    public void Dispose() {}
}
public sealed class LateFrameWire : IWire {
    readonly Queue<int> bytes=new Queue<int>();
    public LateFrameWire(){foreach(char c in "READY UNO_FAN_V2 25000\n")bytes.Enqueue(c);}
    public bool IsOpen {get{return true;}}
    public int ReadByte(){int b=bytes.Dequeue();if(b==10)Thread.Sleep(50);return b;}
    public void Write(string text){}
    public void Dispose(){}
}
public static class ProtocolTests {
    static void Assert(bool value,string message) { if(!value) throw new Exception(message); }
    static void Fails(Action action,string message) { bool failed=false; try { action(); } catch { failed=true; } Assert(failed,message); }
    static FanSession Ready(FakeWire wire) {
        wire.Feed("noise\nREADY UNO_FAN_V2 25000\n"); var session=new FanSession(wire); session.Identify(100); return session;
    }
    public static string[] Run() {
        var results=new List<string>();
        var wrong=new FakeWire(); wrong.Feed("READY UNO_FAN_V2 25001\n");
        var wrongSession=new FanSession(wrong); Fails(delegate { wrongSession.Identify(20); },"Wrong board must fail");
        Fails(delegate { wrongSession.Command("SET 30",20); },"Unidentified command must fail");
        Assert(wrong.Writes.Count==0,"Wrong port received a write"); results.Add("PASS wrong identity -> zero writes, including command guard");
        var wire=new FakeWire(); var session=Ready(wire); wire.AutoAck=true;
        foreach(int duty in new int[]{30,50,70,100,0}) Assert(session.Command("SET "+duty,100)=="OK DUTY "+duty,"Sequence ACK");
        Assert(wire.Writes.Count==5,"Single session sequence"); results.Add("PASS 30/50/70/100/0 acknowledged in one session");
        Fails(delegate { session.Command("SET 101",100); },"101 accepted");
        Fails(delegate { session.Command("SET 030",100); },"Noncanonical integer accepted");
        Fails(delegate { session.Command("SET 3\nSET 100",100); },"Injection accepted");
        Assert(wire.Writes.Count==5,"Invalid command written"); results.Add("PASS range, canonical integer, command injection rejected before write");
        foreach(string reply in new string[]{"OK DUTY 70\n","OK DUTY 030\n","ERR RANGE\n","OK DUTY 101\n"}) {
            var bad=new FakeWire(); var badSession=Ready(bad); bad.Feed(reply);
            Fails(delegate { badSession.Command("SET 30",30); },"Bad ACK accepted");
        } results.Add("PASS mismatch, malformed ACK, ERR, out-of-range ACK fail");
        var longWire=new FakeWire(); longWire.Feed(new string('X',65)+"\n");
        Fails(delegate { new FanSession(longWire).Identify(100); },"Oversized frame accepted");
        var nonAscii=new FakeWire(); nonAscii.Feed("\u00e9\n");
        Fails(delegate { new FanSession(nonAscii).Identify(100); },"Non-ASCII accepted"); results.Add("PASS oversized/non-ASCII frame rejected");
        var flood=new FakeWire(); for(int i=0;i<64;i++) flood.Feed("noise\n"); flood.Feed("READY UNO_FAN_V2 25000\n");
        Fails(delegate { new FanSession(flood).Identify(100); },"Unlimited frame flood accepted"); results.Add("PASS identity frame limit is finite");
        var silent=new FakeWire(); var timer=Stopwatch.StartNew();
        Fails(delegate { new FanSession(silent).Identify(30); },"Silent wire accepted");
        Assert(timer.ElapsedMilliseconds<250,"Total deadline was not bounded"); results.Add("PASS silence total deadline bounded");
        var cleanupWire=new FakeWire(); var cleanupSession=Ready(cleanupWire); cleanupWire.AutoAck=true;
        try { cleanupSession.Command("SET 30",50); throw new Exception("synthetic acquisition failure"); }
        catch {} finally { Assert(cleanupSession.Command("SET 0",50)=="OK DUTY 0","Cleanup ACK failed"); }
        Assert(cleanupWire.Writes[1]=="SET 0\n","Failure cleanup missing"); results.Add("PASS synthetic acquisition failure still requests zero");
        cleanupWire.CleanupFails=true;
        Fails(delegate { cleanupSession.Command("SET 0",50); },"Cleanup failure falsely acknowledged"); results.Add("PASS cleanup error cannot be reported as zero acknowledged");
        Assert(Encoding.ASCII.GetString(ScopeVisa.BlockPayload(Encoding.ASCII.GetBytes("#13abc\n")))=="abc","SCPI payload wrong");
        foreach(string bad in new string[]{"#13ab","#0abc","#xabc","#13abcjunk","#2x3abc"})
            Fails(delegate { ScopeVisa.BlockPayload(Encoding.ASCII.GetBytes(bad)); },"Corrupt block accepted");
        results.Add("PASS definite block parsing plus truncation/indefinite/invalid length/trailing corruption");
        return results.ToArray();
    }
}
