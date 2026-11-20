// Walks the stage-object factory table: table[category] -> array of constructor pointers indexed by type.
// For each constructor, reports the vftable class names it (and the functions it calls) assigns.
// args: <outFile> <tableAddr> <categories> <maxTypes>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.util.*;
import java.util.regex.*;

public class MapFactory extends GhidraScript {
    DecompInterface di;
    Map<Address, String> cache = new HashMap<>();
    Pattern vt = Pattern.compile("([A-Za-z_][A-Za-z0-9_]*)::vftable");

    String classes(Function f, int depth) throws Exception {
        if (f == null) return "?";
        if (cache.containsKey(f.getEntryPoint()) && depth == 0) return cache.get(f.getEntryPoint());
        DecompileResults r = di.decompileFunction(f, 60, monitor);
        if (!r.decompileCompleted()) return "decompile failed";
        String c = r.getDecompiledFunction().getC();
        LinkedHashSet<String> found = new LinkedHashSet<>();
        Matcher m = vt.matcher(c);
        while (m.find()) found.add(m.group(1));
        if (found.isEmpty() && depth < 2) {
            for (Function callee : f.getCalledFunctions(monitor)) {
                String s = classes(callee, depth + 1);
                if (!s.isEmpty() && !s.startsWith("?") && !s.startsWith("decompile")) found.add("via " + callee.getName() + ": " + s);
            }
        }
        String res = String.join(", ", found);
        if (depth == 0) cache.put(f.getEntryPoint(), res);
        return res;
    }

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Address table = toAddr(a[1]);
        int cats = Integer.parseInt(a[2]);
        int maxTypes = Integer.parseInt(a[3]);
        Memory mem = currentProgram.getMemory();
        di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        boolean flat = cats == 0;                 // 0 categories = the table itself is the constructor array
        for (int cat = 0; cat < (flat ? 1 : cats); cat++) {
            long sub = flat ? table.getOffset() : mem.getLong(table.add(cat * 8L));
            out.println("category " + cat + " -> " + Long.toHexString(sub));
            if (sub == 0) continue;
            Address subA = toAddr(sub);
            for (int t = 0; t < maxTypes; t++) {
                long fp;
                try { fp = mem.getLong(subA.add(t * 8L)); } catch (Exception e) { break; }
                if (fp == 0) { out.println("  type " + t + ": (none)"); continue; }
                Address fa;
                try { fa = toAddr(fp); } catch (Exception e) { break; }
                Function f = getFunctionAt(fa);
                if (f == null || !currentProgram.getMemory().getBlock(fa).isExecute()) { out.println("  type " + t + ": not code (" + Long.toHexString(fp) + "), stop"); break; }
                out.println("  type " + t + ": " + f.getName() + "  " + classes(f, 0));
            }
        }
        out.close();
        di.dispose();
        println("done");
    }
}
