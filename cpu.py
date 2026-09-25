"""
Assembler + simulator for the custom 8-bit CPU described in
'8-bit CPU Design for Pong Game Development' (Rev A).

ISA summary (derived + verified against the Fibonacci benchmark in the doc):

16-bit instruction word, opcode = bits[15:12]

  ALU_OP  0000  we=b11  alu=b10-8  wd=b7-6  ra=b5-4  rb=b3-2   (bits1-0 unused)
  JC      0110  we=0                                addr = b7-0
  JZ      0111  we=0                                addr = b7-0
  JMP     1000  we=0                                addr = b7-0
  STORE   1001  we=0    (unused)      (unused) ra=b5-4(data) rb=b3-2(addr)
  LOAD    1010  we=1    (unused)      wd=b7-6(dest) (unused) rb=b3-2(addr)
  LDI     1011  we=1    (unused,3b)   data = b7-0 (dest reg is forced by
                                       the VALUE's own top 2 bits: 0-63->R0,
                                       64-127->R1,128-191->R2,192-255->R3)

ALU_Control: 0 ADD 1 SUB 2 AND 3 OR 4 XOR 5 NOT 6 SHL 7 SHR
Registers:   R0=00 R1=01 R2=10 R3=11

Memory map (documented assumption, section 5.1 of the PDF):
  address 0x00-0x7F  -> real RAM (game state)
  STORE  0x80-0xFF   -> VRAM row register (row = addr & 0x07), one row of the
                         8x8 LED matrix, bit(n) = column n lit
  LOAD   0x80-0xFF   -> controller byte (buttons), RAM is not touched
                         bit0=P1_UP bit1=P1_DOWN bit2=P2_UP bit3=P2_DOWN (1=pressed)
"""

R0, R1, R2, R3 = 0, 1, 2, 3
REGNAME = {R0: "R0", R1: "R1", R2: "R2", R3: "R3"}

ADD, SUB, AND, OR, XOR, NOT, SHL, SHR = range(8)
ALUNAME = {ADD: "ADD", SUB: "SUB", AND: "AND", OR: "OR", XOR: "XOR",
           NOT: "NOT", SHL: "SHL", SHR: "SHR"}


class Asm:
    def __init__(self):
        self.prog = []          # list of dicts describing each real instruction
        self.labels = {}        # name -> address (index)
        self.pending_jumps = [] # (index, label, kind)

    # ---- low level emit ----
    def _emit(self, **kw):
        self.prog.append(kw)
        return len(self.prog) - 1

    def here(self):
        return len(self.prog)

    def label(self, name):
        assert name not in self.labels, f"duplicate label {name}"
        self.labels[name] = self.here()

    def comment(self, text):
        # attach a standalone comment (no-op instruction marker not needed;
        # we just stash it to print later against the *next* instruction)
        self._next_comment = text

    def _c(self):
        c = getattr(self, "_next_comment", None)
        self._next_comment = None
        return c

    # ---- real instructions ----
    def alu(self, op, ra, rb, wd, we=True, note=None):
        self._emit(kind="ALU", op=op, ra=ra, rb=rb, wd=wd, we=we,
                    note=note or self._c())

    def cmp(self, ra, rb, note=None):
        """SUB ra,rb, discard result, only used for the Z flag."""
        self._emit(kind="ALU", op=SUB, ra=ra, rb=rb, wd=0, we=False,
                    note=note or self._c() or f"CMP {REGNAME[ra]},{REGNAME[rb]}")

    def store(self, ra_data, rb_addr, note=None):
        self._emit(kind="STORE", ra=ra_data, rb=rb_addr, note=note or self._c())

    def load(self, rd, rb_addr, note=None):
        self._emit(kind="LOAD", rd=rd, rb=rb_addr, note=note or self._c())

    def jmp(self, label, note=None):
        self._emit(kind="JMP", label=label, note=note or self._c())

    def jz(self, label, note=None):
        self._emit(kind="JZ", label=label, note=note or self._c())

    def jc(self, label, note=None):
        self._emit(kind="JC", label=label, note=note or self._c())

    def ldi_raw(self, value, note=None):
        """Emit a single real LDI. Destination is forced by value's magnitude."""
        value &= 0xFF
        self._emit(kind="LDI", value=value, note=note or self._c())
        return value >> 6  # register that received it

    def imm(self, value, dst, note=None):
        """Load an 8-bit immediate into an arbitrary register dst.
        Emits 1 instruction if dst already matches the value's natural
        register, otherwise 2 (LDI to natural reg + OR-copy to dst)."""
        value &= 0xFF
        natural = value >> 6
        tag = note or self._c()
        if natural == dst:
            self.ldi_raw(value, note=tag)
        else:
            self.ldi_raw(value, note=(tag + " (stage)") if tag else None)
            self.alu(OR, natural, natural, dst,
                     note=(tag + " (copy)") if tag else f"copy -> {REGNAME[dst]}")

    def mov(self, src, dst, note=None):
        self.alu(OR, src, src, dst, note=note or self._c() or f"MOV {REGNAME[src]}->{REGNAME[dst]}")

    # ---- assembly ----
    def assemble(self):
        words = []
        for i, ins in enumerate(self.prog):
            k = ins["kind"]
            if k == "ALU":
                w = (0 << 12) | ((1 if ins["we"] else 0) << 11) | (ins["op"] << 8) \
                    | (ins["wd"] << 6) | (ins["ra"] << 4) | (ins["rb"] << 2)
            elif k == "STORE":
                w = (0x9 << 12) | (ins["ra"] << 4) | (ins["rb"] << 2)
            elif k == "LOAD":
                w = (0xA << 12) | (1 << 11) | (ins["rd"] << 6) | (ins["rb"] << 2)
            elif k == "LDI":
                w = (0xB << 12) | (1 << 11) | ins["value"]
            elif k in ("JMP", "JZ", "JC"):
                addr = self.labels[ins["label"]]
                assert 0 <= addr <= 0xFF, f"jump target out of range: {ins['label']}={addr}"
                opc = {"JMP": 0x8, "JZ": 0x7, "JC": 0x6}[k]
                w = (opc << 12) | addr
            else:
                raise ValueError(k)
            words.append(w & 0xFFFF)
        return words

    def listing(self, words):
        lines = []
        addr_to_label = {v: k for k, v in self.labels.items()}
        for i, (ins, w) in enumerate(zip(self.prog, words)):
            lab = addr_to_label.get(i, "")
            mnem = self._mnemonic(ins)
            note = ins.get("note") or ""
            lines.append(f"{i:3d} (0x{i:02X})  {w:04X}  {lab:14s} {mnem:28s} ; {note}")
        return "\n".join(lines)

    def _mnemonic(self, ins):
        k = ins["kind"]
        if k == "ALU":
            we = "" if ins["we"] else " (flags only)"
            return f"{ALUNAME[ins['op']]} {REGNAME[ins['ra']]},{REGNAME[ins['rb']]} -> {REGNAME[ins['wd']]}{we}"
        if k == "STORE":
            return f"STORE {REGNAME[ins['ra']]}, ({REGNAME[ins['rb']]})"
        if k == "LOAD":
            return f"LOAD {REGNAME[ins['rd']]}, ({REGNAME[ins['rb']]})"
        if k == "LDI":
            v = ins["value"]
            return f"LDI 0x{v:02X} (-> {REGNAME[v>>6]})"
        if k in ("JMP", "JZ", "JC"):
            return f"{k} {ins['label']}"
        return "?"