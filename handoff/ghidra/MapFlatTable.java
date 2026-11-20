// Walks a flat constructor table (pointer per index) and names the class each constructor builds (vftables).
// args: <outFile> <tableAddr> <count>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.util.*;
import java.util.regex.*;

public class MapFlatTable extends GhidraScript {
    DecompInterface di;
    Pattern vt = Pattern.compile("([A-Za-z_][A-Za-z0-9_]*)::vftable");

    String classes(Function f, int depth) throws Exception {
        DecompileResults r = di.decompileFunction(f, 60, monitor);
        if (!r.decompileCompleted()) return "?";
        LinkedHashSet<String> found = new LinkedHashSet<>();
        Matcher m = vt.matcher(r.getDecompiledFunction().getC());
        while (m.find()) found.add(m.group(1));
        if (found.isEmpty() && depth < 2)
            for (Function c : f.getCalledFunctions(monitor)) {
                String s = classes(c, depth + 1);
                if (!s.isEmpty() && !s.equals("?")) found.add("via " + c.getName() + ": " + s);
            }
        return String.join(", ", found);
    }

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Address t = toAddr(a[1]);
        int n = Integer.parseInt(a[2]);
        Memory mem = currentProgram.getMemory();
        di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        for (int i = 0; i < n; i++) {
            long p = mem.getLong(t.add(i * 8L));
            if (p == 0) { out.println("kind " + i + ": (none)"); continue; }
            Address fa = toAddr(p);
            MemoryBlock blk = mem.getBlock(fa);
            if (blk == null || !blk.isExecute()) { out.println("kind " + i + ": not code, stop"); break; }
            Function f = getFunctionAt(fa);
            out.println("kind " + i + ": " + (f == null ? "?" : f.getName() + "  " + classes(f, 0)));
        }
        out.close();
        di.dispose();
    }
}
