// Decompiles every function that references one of the given data addresses (reads or writes).
// args: <outFile> <addr1~addr2~...> [maxFunctions]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class XrefsTo extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        int max = a.length > 2 ? Integer.parseInt(a[2]) : 40;
        Map<Function, Set<String>> why = new TreeMap<>(Comparator.comparing(Function::getEntryPoint));
        ReferenceManager rm = currentProgram.getReferenceManager();
        for (String s : a[1].split("~")) {
            Address target = toAddr(s);
            for (Reference r : rm.getReferencesTo(target)) {
                Function f = getFunctionContaining(r.getFromAddress());
                if (f == null) continue;
                why.computeIfAbsent(f, k -> new TreeSet<>()).add(s + " " + r.getReferenceType() + " @" + r.getFromAddress());
            }
        }
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(new FileWriter(a[0]))) {
            out.println("// " + why.size() + " functions");
            for (var e : why.entrySet()) out.println("//   " + e.getKey().getName() + " " + e.getValue());
            int n = 0;
            for (var e : why.entrySet()) {
                if (n++ >= max) break;
                DecompileResults res = d.decompileFunction(e.getKey(), 60, monitor);
                out.println("\n// ===== " + e.getKey().getName() + " @ " + e.getKey().getEntryPoint());
                out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed");
            }
        }
    }
}
