// Decompiles every function whose entry lies in [from, to): DecompileRange.java <out> <from> <to>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DecompileRange extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        var from = toAddr(a[1]);
        var to = toAddr(a[2]);
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        try (PrintWriter w = new PrintWriter(new FileWriter(a[0]))) {
            for (Function f : currentProgram.getFunctionManager().getFunctions(from, true)) {
                if (f.getEntryPoint().compareTo(to) >= 0) break;
                DecompileResults r = di.decompileFunction(f, 60, monitor);
                w.println("// ===== " + f.getName() + " @ " + f.getEntryPoint());
                w.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// (failed)");
            }
        }
    }
}
