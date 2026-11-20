// Decompiles the functions at the given addresses, plus (optionally) every function that calls them.
// args: <outFile> <addr1~addr2~...> [callers]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DecompileAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        boolean callers = a.length > 2 && a[2].equals("callers");
        Map<Function, String> todo = new TreeMap<>(Comparator.comparing(Function::getEntryPoint));
        for (String s : a[1].split("~")) {
            Function f = getFunctionAt(toAddr(s.trim()));
            if (f == null) { println("no function at " + s); continue; }
            todo.putIfAbsent(f, "requested");
            if (callers) {
                for (Reference r : getReferencesTo(f.getEntryPoint())) {
                    Function c = getFunctionContaining(r.getFromAddress());
                    if (c != null) todo.putIfAbsent(c, "calls " + f.getName());
                }
            }
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        for (Map.Entry<Function, String> e : todo.entrySet()) {
            out.println("\n// ===== " + e.getKey().getName() + " @ " + e.getKey().getEntryPoint() + "  (" + e.getValue() + ")");
            DecompileResults res = di.decompileFunction(e.getKey(), 120, monitor);
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed");
        }
        out.close();
        di.dispose();
        println("wrote " + todo.size() + " functions");
    }
}

