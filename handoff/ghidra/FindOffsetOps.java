// Lists instructions whose text matches a regex: FindOffsetOps.java <out> <regexFile>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.regex.*;

public class FindOffsetOps extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Pattern p = Pattern.compile(new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(a[1]))).trim());
        try (PrintWriter w = new PrintWriter(new FileWriter(a[0]))) {
            InstructionIterator it = currentProgram.getListing().getInstructions(true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                String s = ins.toString();
                if (p.matcher(s).find()) {
                    Function f = getFunctionContaining(ins.getAddress());
                    w.println(ins.getAddress() + "  " + (f == null ? "?" : f.getName()) + "  " + s);
                }
            }
        }
    }
}

