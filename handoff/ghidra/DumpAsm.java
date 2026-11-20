// Lists instructions. args: <outFile> <addr~count~addr~count...>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import java.io.*;

public class DumpAsm extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        String[] p = a[1].split("~");
        try (PrintWriter w = new PrintWriter(new FileWriter(a[0]))) {
            for (int k = 0; k + 1 < p.length; k += 2) {
                var addr = toAddr(p[k]);
                int n = Integer.parseInt(p[k + 1]);
                if (getInstructionAt(addr) == null) disassemble(addr);
                Instruction ins = getInstructionAt(addr);
                w.println("== " + p[k]);
                for (int i = 0; i < n && ins != null; i++, ins = ins.getNext())
                    w.println(ins.getAddress() + "  " + ins);
            }
        }
    }
}
