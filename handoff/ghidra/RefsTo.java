// Lists every reference to an address, plus raw 8-byte pointers to it in memory: RefsTo.java <out> <addr>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class RefsTo extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Address t = toAddr(a[1]);
        try (PrintWriter w = new PrintWriter(new FileWriter(a[0]))) {
            for (Reference r : getReferencesTo(t))
                w.println("ref " + r.getFromAddress() + " " + r.getReferenceType());
            long v = t.getOffset();
            byte[] pat = new byte[8];
            for (int i = 0; i < 8; i++) pat[i] = (byte) (v >>> (8 * i));
            Address s = currentProgram.getMinAddress();
            while (s != null) {
                s = find(s, pat);
                if (s == null) break;
                w.println("ptr " + s);
                s = s.add(1);
            }
        }
    }
}
