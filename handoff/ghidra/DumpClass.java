// Decompiles every method in the vftables of the named classes (and functions referencing those vftables).
// args: <outFile> <Class1~Class2~...> [maxSlots]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DumpClass extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        int maxSlots = a.length > 2 ? Integer.parseInt(a[2]) : 80;
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        Memory mem = currentProgram.getMemory();
        Set<Address> done = new HashSet<>();
        for (String cls : a[1].split("~")) {
            List<Symbol> syms = new ArrayList<>();
            for (Symbol s : currentProgram.getSymbolTable().getAllSymbols(true)) {
                if (s.getName().equals("vftable") && s.getParentNamespace() != null && s.getParentNamespace().getName().equals(cls))
                    syms.add(s);
            }
            if (syms.isEmpty()) { out.println("// no vftable for " + cls); continue; }
            for (Symbol vt : syms) {
                Address base = vt.getAddress();
                out.println("\n// ################ " + cls + "::vftable @ " + base);
                for (int i = 0; i < maxSlots; i++) {
                    long p;
                    try { p = mem.getLong(base.add(i * 8L)); } catch (Exception e) { break; }
                    Address fa = toAddr(p);
                    MemoryBlock blk = mem.getBlock(fa);
                    if (blk == null || !blk.isExecute()) break;
                    Function f = getFunctionAt(fa);
                    if (f == null) { out.println("// slot " + i + " (+0x" + Integer.toHexString(i * 8) + "): no function at " + fa); continue; }
                    out.println("\n// ===== slot " + i + " (+0x" + Integer.toHexString(i * 8) + ") " + f.getName() + " @ " + fa);
                    if (!done.add(fa)) { out.println("// (already printed)"); continue; }
                    DecompileResults r = di.decompileFunction(f, 60, monitor);
                    out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// decompile failed");
                }
            }
        }
        out.close();
        di.dispose();
        println("done");
    }
}
