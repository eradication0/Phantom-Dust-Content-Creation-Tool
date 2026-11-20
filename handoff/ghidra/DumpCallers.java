// Decompiles every function that calls one of the named functions (imports included).
// args: <outFile> <name1,name2,...>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.*;

public class DumpCallers extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Set<String> names = new HashSet<>(Arrays.asList(a[1].split(",")));
        Map<Function, Set<String>> why = new TreeMap<>(Comparator.comparing(Function::getEntryPoint));
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            for (Function callee : f.getCalledFunctions(monitor)) {
                Function target = callee.isThunk() ? callee.getThunkedFunction(true) : callee;
                if (names.contains(callee.getName()) || (target != null && names.contains(target.getName()))) {
                    if (!callee.isThunk() || f != callee) why.computeIfAbsent(f, k -> new TreeSet<>()).add(callee.getName());
                }
            }
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        for (Map.Entry<Function, Set<String>> e : why.entrySet()) {
            Function f = e.getKey();
            if (f.isThunk()) continue;
            out.println("\n// ===== " + f.getName() + " @ " + f.getEntryPoint() + "  calls " + e.getValue());
            DecompileResults res = di.decompileFunction(f, 120, monitor);
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed");
        }
        out.close();
        di.dispose();
        println("wrote " + why.size() + " functions");
    }
}
