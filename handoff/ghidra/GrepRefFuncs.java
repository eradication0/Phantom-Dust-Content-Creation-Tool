// Decompiles every function that references an address and prints the C lines matching a regex:
// GrepRefFuncs.java <out> <addr> <regexFile>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;
import java.util.regex.*;

public class GrepRefFuncs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        var target = toAddr(a[1]);
        Pattern p = Pattern.compile(new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(a[2]))).trim());
        Set<Function> funcs = new TreeSet<>(Comparator.comparing(Function::getEntryPoint));
        for (Reference r : getReferencesTo(target)) {
            Function f = getFunctionContaining(r.getFromAddress());
            if (f != null) funcs.add(f);
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        try (PrintWriter w = new PrintWriter(new FileWriter(a[0]))) {
            w.println("// " + funcs.size() + " functions");
            for (Function f : funcs) {
                DecompileResults res = di.decompileFunction(f, 60, monitor);
                if (!res.decompileCompleted()) continue;
                String[] lines = res.getDecompiledFunction().getC().split("\n");
                for (String line : lines)
                    if (p.matcher(line).find()) w.println(f.getName() + ": " + line.trim());
            }
        }
    }
}
