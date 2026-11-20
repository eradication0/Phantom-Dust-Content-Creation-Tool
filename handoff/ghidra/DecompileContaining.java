// Decompiles the functions that contain the given addresses.
// args: <outFile> <addr1~addr2~...>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.*;

public class DecompileContaining extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        Set<Function> done = new HashSet<>();
        try (PrintWriter out = new PrintWriter(new FileWriter(a[0]))) {
            for (String s : a[1].split("~")) {
                Function f = getFunctionContaining(toAddr(s));
                if (f == null) { out.println("// " + s + ": no function"); continue; }
                out.println("// " + s + " is in " + f.getName() + " @ " + f.getEntryPoint());
                if (!done.add(f)) continue;
                DecompileResults r = d.decompileFunction(f, 60, monitor);
                out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// decompile failed");
            }
        }
    }
}
