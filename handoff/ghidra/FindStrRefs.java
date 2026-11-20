// Finds raw text (ASCII and UTF-16LE) anywhere in the program, then decompiles every function that references it.
// Works even where Ghidra didn't define the string as data.
// args: <outFile> <needle1~needle2~...> [maxFunctions]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public class FindStrRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        String[] needles = a[1].split("~");
        int max = a.length > 2 ? Integer.parseInt(a[2]) : 60;
        Memory mem = currentProgram.getMemory();
        Map<Function, Set<String>> why = new TreeMap<>(Comparator.comparing(Function::getEntryPoint));

        for (String needle : needles) {
            for (byte[] pattern : new byte[][] { needle.getBytes(StandardCharsets.US_ASCII), needle.getBytes(StandardCharsets.UTF_16LE) }) {
                Address start = mem.getMinAddress();
                while (start != null) {
                    Address hit = mem.findBytes(start, pattern, null, true, monitor);
                    if (hit == null) break;
                    // Walk back to the start of the string so references to it are found.
                    Address s = hit;
                    int step = pattern.length == needle.length() ? 1 : 2;
                    for (int i = 0; i < 256; i++) {
                        Address prev = s.subtract(step);
                        byte b = mem.getByte(prev);
                        byte b2 = step == 2 ? mem.getByte(prev.add(1)) : 0;
                        if (b < 0x20 || b > 0x7e || b2 != 0) break;
                        s = prev;
                    }
                    String text = readString(s, step);
                    for (Reference r : getReferencesTo(s)) {
                        Function f = getFunctionContaining(r.getFromAddress());
                        if (f != null) why.computeIfAbsent(f, k -> new TreeSet<>()).add('"' + text + '"');
                    }
                    start = hit.add(1);
                }
            }
        }

        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        out.println("// " + why.size() + " functions (decompiling up to " + max + ")");
        for (Map.Entry<Function, Set<String>> e : why.entrySet()) out.println("//   " + e.getKey().getName() + " @ " + e.getKey().getEntryPoint() + "  " + e.getValue());
        int n = 0;
        for (Function f : why.keySet()) {
            if (n++ >= max) break;
            out.println("\n// ===== " + f.getName() + " @ " + f.getEntryPoint() + "  " + why.get(f));
            DecompileResults res = di.decompileFunction(f, 120, monitor);
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed");
        }
        out.close();
        di.dispose();
        println("wrote " + why.size() + " functions");
    }

    private String readString(Address s, int step) throws Exception {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 160; i++) {
            byte b = getByte(s.add((long) i * step));
            if (b == 0) break;
            sb.append((char) b);
        }
        return sb.toString();
    }
}
