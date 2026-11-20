// Decompiles every function that calls one of the given imports or references a string
// containing one of the given substrings. Writes C to the output file.
// args: <outFile> <import1,import2,...> <substr1~substr2~...>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import java.io.*;
import java.util.*;

public class DumpRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        Set<String> imports = new HashSet<>(Arrays.asList(a[1].split(",")));
        String[] subs = a.length > 2 ? a[2].split("~") : new String[0];
        Map<Function, Set<String>> why = new TreeMap<>(Comparator.comparing(Function::getEntryPoint));

        // Callers of imports (through the thunk or the IAT pointer).
        SymbolTable st = currentProgram.getSymbolTable();
        for (Symbol s : st.getExternalSymbols()) {
            if (!imports.contains(s.getName())) continue;
            List<Address> targets = new ArrayList<>();
            targets.add(s.getAddress());
            for (Reference r : getReferencesTo(s.getAddress())) targets.add(r.getFromAddress());
            for (Address t : targets) {
                Function thunk = getFunctionAt(t);
                List<Address> sites = new ArrayList<>();
                for (Reference r : getReferencesTo(t)) sites.add(r.getFromAddress());
                if (thunk != null) for (Reference r : getReferencesTo(thunk.getEntryPoint())) sites.add(r.getFromAddress());
                for (Address site : sites) {
                    Function f = getFunctionContaining(site);
                    if (f != null && f != thunk) why.computeIfAbsent(f, k -> new TreeSet<>()).add("calls " + s.getName());
                }
            }
        }

        // Functions referencing matching strings (ASCII or UTF-16).
        for (Data d : currentProgram.getListing().getDefinedData(true)) {
            if (!(d.getValue() instanceof String)) continue;
            String v = (String) d.getValue();
            for (String sub : subs) {
                if (!sub.isEmpty() && v.contains(sub)) {
                    for (Reference r : getReferencesTo(d.getAddress())) {
                        Function f = getFunctionContaining(r.getFromAddress());
                        if (f != null) why.computeIfAbsent(f, k -> new TreeSet<>()).add("str \"" + (v.length() > 80 ? v.substring(0, 80) : v) + "\"");
                    }
                }
            }
        }

        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        out.println("// " + why.size() + " functions");
        for (Map.Entry<Function, Set<String>> e : why.entrySet()) {
            Function f = e.getKey();
            out.println("\n// ===== " + f.getName() + " @ " + f.getEntryPoint());
            for (String w : e.getValue()) out.println("//   " + w);
            DecompileResults res = di.decompileFunction(f, 120, monitor);
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// decompile failed: " + res.getErrorMessage());
        }
        di.dispose();
        out.close();
        println("wrote " + why.size() + " functions to " + a[0]);
    }
}

