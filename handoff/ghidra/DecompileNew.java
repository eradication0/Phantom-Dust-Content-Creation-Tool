// Creates functions at the given addresses if missing (not saved: run with -readOnly) and decompiles them.
// args: <outFile> <addr1~addr2~...>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DecompileNew extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        try (PrintWriter w = new PrintWriter(new FileWriter(a[0]))) {
            for (String s : a[1].split("~")) {
                var addr = toAddr(s.trim());
                Function f = getFunctionAt(addr);
                if (f == null) { disassemble(addr); f = createFunction(addr, null); }
                if (f == null) { w.println("// cannot create at " + s); continue; }
                w.println("// ===== " + f.getName() + " @ " + f.getEntryPoint());
                w.println(di.decompileFunction(f, 60, monitor).getDecompiledFunction().getC());
            }
        }
    }
}
