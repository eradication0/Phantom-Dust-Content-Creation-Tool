// Decompiles the functions at the given addresses, plus (optionally) everything they call directly.
// args: <outFile> <addr1+addr2+...> [depth]  (use + between items: the .bat launcher splits on commas)   (depth 0 = only the named functions; default 1)
// An item written as refADDR means "every function that references ADDR" (handy for strings Ghidra left undefined).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.*;

public class DumpFuncs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        int depth = a.length > 2 ? Integer.parseInt(a[2]) : 1;
        Set<Function> done = new LinkedHashSet<>();
        List<Function> level = new ArrayList<>();
        for (String s : a[1].split("[+,]")) {
            if (s.startsWith("ref")) { // refADDR: every function that references ADDR (e.g. an undefined string)
                for (ghidra.program.model.symbol.Reference r : getReferencesTo(toAddr(s.substring(3)))) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    if (f != null) level.add(f);
                }
                continue;
            }
            Function f = getFunctionAt(toAddr(s));
            if (f == null) f = getFunctionContaining(toAddr(s));
            if (f != null) level.add(f); else println("no function at " + s);
        }
        for (int d = 0; d <= depth && !level.isEmpty(); d++) {
            List<Function> next = new ArrayList<>();
            for (Function f : level) {
                if (f.isThunk() || f.isExternal() || !done.add(f)) continue;
                for (Function c : f.getCalledFunctions(monitor)) next.add(c);
            }
            level = next;
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        for (Function f : done) {
            out.println("\n// ===== " + f.getName() + " @ " + f.getEntryPoint());
            DecompileResults res = di.decompileFunction(f, 120, monitor);
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed");
        }
        out.close();
        di.dispose();
        println("wrote " + done.size() + " functions");
    }
}
