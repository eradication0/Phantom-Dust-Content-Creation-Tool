// Dumps qwords around an address, with strings they point at: DumpQwords.java <out> <addr> <before> <after>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import java.io.*;

public class DumpQwords extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Address c = toAddr(a[1]);
        int b = Integer.parseInt(a[2]), n = Integer.parseInt(a[3]);
        try (PrintWriter w = new PrintWriter(new FileWriter(a[0]))) {
            for (int i = -b; i < n; i++) {
                Address at = c.add(i * 8L);
                long v = getLong(at);
                String s = "";
                try {
                    Address p = toAddr(v);
                    if (currentProgram.getMemory().contains(p)) {
                        StringBuilder sb = new StringBuilder();
                        for (int k = 0; k < 40; k++) { byte ch = getByte(p.add(k)); if (ch == 0) break; if (ch < 32 || ch > 126) { sb.setLength(0); break; } sb.append((char) ch); }
                        s = sb.toString();
                        var f = getFunctionAt(p);
                        if (f != null) s = "fn " + f.getName();
                    }
                } catch (Exception e) { }
                w.println(at + "  " + Long.toHexString(v) + "  " + s);
            }
        }
    }
}
