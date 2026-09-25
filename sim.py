from cpu import Asm, R0, R2
a = Asm()
a.label("LOOP")
a.imm(0x80, R2, note="R2 = 0x80 (Controller Input / VRAM Row 0)")
a.load(R0, R2, note="Store the buttons at R0")
a.store(R0, R2, note="Light up the corresponding pixel through VRAM")
a.jmp("LOOP", note="loop")
# Hex Code Production
words = a.assemble()
print("v2.0 raw")
for word in words:
    print(f"{word:04X}")
