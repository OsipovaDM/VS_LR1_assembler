import sys
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple, Union
from interpreter import SimpleAssembler

StageName = str  # 'IF', 'ID', 'EX', 'MEM', 'WB'
@dataclass  # служебные методы: инициализация, отображение, сравнение и пр для полей
class PipelineInstruction:
    """Состояние одной инструкции в конвейере."""
    addr: int
    instr: str
    operands: List[str]
    stage: StageName
    reads: Set[Tuple[str, Union[int, str]]]
    writes: Set[Tuple[str, Union[int, str]]]
    is_branch: bool = False
    branch_target: Optional[int] = None
    result: Optional[int] = None
    extra: Optional[dict] = None
    # Для многотактных операций (уровень C)
    ex_remaining_cycles: int = 0  # оставшиеся такты на стадии EX

class PipelineSimulator(SimpleAssembler):
    """
    Интерпретатор ISA из lab1, расширенный конвейерной моделью (lab2, вариант 9).
    Реализуется пятистадийный конвейер IF‑ID‑EX‑MEM‑WB с:
    - обнаружением RAW‑зависимостей по регистрам и флагу Z (stall),
    - конфликтах по управлению для JMP / JZ / JNZ (flush),
    - сбором основной статистики: такты, инструкции, CPI, stall‑ы и flush‑и.
    """
    STAGES: List[StageName] = ["IF", "ID", "EX", "MEM", "WB"]

    def __init__(self):
        super().__init__()
        self.cycle_count: int = 0
        self.commit_count: int = 0
        self.data_stalls: int = 0
        self.control_flushes: int = 0
        # Дополнительная статистика для уровня C
        self.ex_stalls: int = 0  # задержки из-за занятости EX

    # ---------- Вспомогательные методы ----------
    def _analyze_instruction(self, addr: int, instr: str, operands: List[str]) -> PipelineInstruction:
        """
        Построение формальных множеств R(I), W(I) и признаков ветвления
        для инструкции 
        """     # (см. требования работы)
        instr = instr.upper()
        reads: Set[Tuple[str, Union[int, str]]] = set()
        writes: Set[Tuple[str, Union[int, str]]] = set()
        is_branch = False
        branch_target: Optional[int] = None

        def reg_obj(num: int) -> Tuple[str, int]:
            return ("reg", num)

        def mem_obj(addr_: int) -> Tuple[str, int]:
            return ("mem", addr_)

        if instr in {"HLT", "NOP"}:
            pass
        elif instr == "MOV":
            if len(operands) != 2:
                raise ValueError("MOV требует 2 операнда")
            dest_type, dest_val = self.parse_operand(operands[0])
            src_type, src_val = self.parse_operand(operands[1])
            if dest_type == "reg":
                writes.add(reg_obj(dest_val))
            elif dest_type == "mem":
                writes.add(mem_obj(dest_val))
            if src_type == "reg":
                reads.add(reg_obj(src_val))
            elif src_type == "mem":
                reads.add(mem_obj(src_val))
        elif instr == "CMP":
            if len(operands) != 2:
                raise ValueError("CMP требует 2 операнда")
            op1_type, op1_val = self.parse_operand(operands[0])
            op2_type, op2_val = self.parse_operand(operands[1])
            if op1_type == "reg":
                reads.add(reg_obj(op1_val))
            if op2_type == "reg":
                reads.add(reg_obj(op2_val))
            writes.add(("flag", "Z"))
        elif instr in {"ADD", "SUB", "MUL", "DIV", "MOD"}:
            if len(operands) != 3:
                raise ValueError(f"{instr} требует 3 операнда")
            dest_type, dest_val = self.parse_operand(operands[0])
            src1_type, src1_val = self.parse_operand(operands[1])
            src2_type, src2_val = self.parse_operand(operands[2])
            if dest_type == "reg":
                writes.add(reg_obj(dest_val))
            if src1_type == "reg":
                reads.add(reg_obj(src1_val))
            if src2_type == "reg":
                reads.add(reg_obj(src2_val))
            writes.add(("flag", "Z"))
        elif instr in {"JMP", "JZ", "JNZ"}:
            if len(operands) != 1:
                raise ValueError(f"{instr} требует 1 операнд")
            op_type, op_val = self.parse_operand(operands[0])
            if op_type != "label":
                raise ValueError(f"{instr} требует метку, получен {operands[0]}")
            if op_val not in self.labels:
                raise ValueError(f"Метка '{op_val}' не найдена")
            is_branch = True
            branch_target = self.labels[op_val]
            if instr in {"JZ", "JNZ"}:
                reads.add(("flag", "Z"))
        else:
            raise ValueError(f"Неизвестная команда '{instr}'")

        return PipelineInstruction(
            addr=addr, instr=instr, operands=operands, stage="IF",
            reads=reads, writes=writes,
            is_branch=is_branch, branch_target=branch_target,
            result=None, extra={}, ex_remaining_cycles=0,
        )

    def _execute_stage_ex(self, pinstr: PipelineInstruction, debug: bool) -> bool:
        """
        Стадия EX: выполнение и вычисление условий/адресов.
        Для многотактных операций (MUL, DIV) результат вычисляется сразу,
        но инструкция остаётся на EX несколько тактов (ex_remaining_cycles).
        """
        instr = pinstr.instr
        operands = pinstr.operands
        addr = pinstr.addr

        if instr == "HLT":
            if debug:
                print(f"[EX @{addr}] HLT")
            return True
        if instr == "NOP":
            if debug:
                print(f"[EX @{addr}] NOP")
            return True
        if instr == "MOV":
            dest_type, dest_val = self.parse_operand(operands[0])
            src_type, src_val = self.parse_operand(operands[1])
            if dest_type == "reg" and src_type == "reg":
                pinstr.result = self.registers[src_val]
                if debug:
                    print(f"[EX @{addr}] MOV R{dest_val} <- R{src_val} (вычислено: {pinstr.result})")
            elif dest_type == "reg" and src_type == "imm":
                pinstr.result = src_val
                if debug:
                    print(f"[EX @{addr}] MOV R{dest_val} <- {src_val}")
            elif dest_type == "mem" and src_type == "reg":
                pinstr.result = self.registers[src_val]
                if debug:
                    print(f"[EX @{addr}] MOV [{dest_val}] <- R{src_val} (значение: {pinstr.result})")
            # MOV reg <- mem: результат формируется на стадии MEM
            return True
        if instr == "CMP":
            op1_type, op1_val = self.parse_operand(operands[0])
            op2_type, op2_val = self.parse_operand(operands[1])
            if op1_type != "reg" or op2_type != "reg":
                raise ValueError("CMP требует два операнда-регистра")
            val1 = self.registers[op1_val]
            val2 = self.registers[op2_val]
            pinstr.extra["z_result"] = (val1 == val2)
            if debug:
                print(f"[EX @{addr}] CMP R{op1_val} ({val1}), R{op2_val} ({val2}) -> Z={pinstr.extra['z_result']}")
            return True
        if instr in {"ADD", "SUB", "MUL", "DIV", "MOD"}:
            dest_type, dest_val = self.parse_operand(operands[0])
            src1_type, src1_val = self.parse_operand(operands[1])
            src2_type, src2_val = self.parse_operand(operands[2])
            if dest_type != "reg" or src1_type != "reg" or src2_type != "reg":
                raise ValueError("Арифметика: все операнды — регистры")

            val1 = self.registers[src1_val]
            val2 = self.registers[src2_val]
            max_num = 0xFFFF
            full_result: int
            pinstr.extra["overflow"] = False
            pinstr.extra["error"] = None

            # Установка латентности для многотактных операций (уровень C)
            if instr in {"MUL", "DIV", "MOD"}:
                # Например, 4 такта на выполнение
                pinstr.ex_remaining_cycles = 3  # после первого такта остаётся 3
            else:
                pinstr.ex_remaining_cycles = 0

            if instr == "ADD":
                if max_num - val1 < val2 or (-max_num + 1 - val1) > val2:
                    full_result = max_num
                    pinstr.extra["overflow"] = True
                    self.running = False
                    if debug:
                        print(f"[EX @{addr}] ADD overflow: {val1} + {val2}")
                else:
                    full_result = val1 + val2
                    if debug:
                        print(f"[EX @{addr}] ADD R{dest_val} <- {val1} + {val2} = {full_result}")
            elif instr == "SUB":
                if val1 < (val2 - max_num + 1) or (max_num + val2) < val1:
                    full_result = max_num
                    pinstr.extra["overflow"] = True
                    self.running = False
                    if debug:
                        print(f"[EX @{addr}] SUB overflow: {val1} - {val2}")
                else:
                    full_result = val1 - val2
                    if debug:
                        print(f"[EX @{addr}] SUB R{dest_val} <- {val1} - {val2} = {full_result}")
            elif instr == "MUL":
                if val2 != 0 and ((max_num // val2) < val1 or (val1 < ((-max_num + 1) // val2))):
                    full_result = max_num
                    pinstr.extra["overflow"] = True
                    self.running = False
                    print(f"[EX @{addr}] MUL overflow: {val1} * {val2}")
                else:
                    full_result = val1 * val2
                    if debug:
                        print(f"[EX @{addr}] MUL R{dest_val} <- {val1} * {val2} = {full_result}")
            elif instr == "DIV":
                if val2 == 0:
                    pinstr.extra["error"] = "Деление на ноль (DIV)"
                    self.running = False
                    full_result = 0
                    print(f"[EX @{addr}] DIV error: деление на ноль")
                elif val1 == -max_num + 1 and val2 == -1:
                    full_result = -max_num
                    pinstr.extra["overflow"] = True
                    self.running = False
                    print(f"[EX @{addr}] DIV overflow")
                else:
                    full_result = val1 // val2
                    if debug:
                        print(f"[EX @{addr}] DIV R{dest_val} <- {val1} / {val2} = {full_result}")
            else:  # MOD
                if val2 == 0:
                    pinstr.extra["error"] = "Деление на ноль (MOD)"
                    self.running = False
                    full_result = 0
                    if debug:
                        print(f"[EX @{addr}] MOD error: деление на ноль")
                else:
                    full_result = val1 % val2
                    if debug:
                        print(f"[EX @{addr}] MOD R{dest_val} <- {val1} % {val2} = {full_result}")

            pinstr.result = full_result
            pinstr.extra["z_flag"] = full_result <= 0
            if pinstr.extra.get('error') or pinstr.extra.get('overflow'):
                return False
            return True
        if instr in {"JMP", "JZ", "JNZ"}:
            if debug:
                print(f"[EX @{addr}] {instr} (решение о переходе — в основном цикле)")
            return True
        raise ValueError(f"Неизвестная команда '{instr}' в EX")

    def _commit_instruction(self, pinstr: PipelineInstruction, debug: bool) -> None:
        """
        Стадия WB: только фиксация уже вычисленного результата в архитектурном
        состоянии (регистры, флаг Z). Вычисление выполняется на EX, доступ к
        памяти — на MEM.
        """
        instr = pinstr.instr
        operands = pinstr.operands
        addr = pinstr.addr

        if instr == "HLT":
            if debug:
                print(f"[WB @{addr}] HLT -> останов.")
            self.running = False
            return
        if instr == "NOP":
            if debug:
                print(f"[WB @{addr}] NOP")
            return
        if instr == "MOV":
            dest_type, dest_val = self.parse_operand(operands[0])
            src_type, src_val = self.parse_operand(operands[1])
            if dest_type == "reg":
                if pinstr.result is None and src_type == "mem":
                    pinstr.result = self.memory[src_val]
                self.registers[dest_val] = pinstr.result
                if debug:
                    print(f"[WB @{addr}] MOV R{dest_val} <- {pinstr.result} (фиксация)")
            return
        if instr == "CMP":
            self.z_flag = pinstr.extra.get("z_result", False)
            if debug:
                print(f"[WB @{addr}] CMP -> Z={self.z_flag} (фиксация)")
            return
        if instr in {"ADD", "SUB", "MUL", "DIV", "MOD"}:
            if pinstr.extra.get("error"):
                if debug:
                    print(f"[WB @{addr}] {instr}: {pinstr.extra['error']}")
                self.running = False
                return
            if pinstr.extra.get("overflow"):
                self.running = False
            dest_type, dest_val = self.parse_operand(operands[0])
            self.registers[dest_val] = pinstr.result
            self.z_flag = pinstr.extra.get("z_flag", False)
            if debug:
                print(f"[WB @{addr}] {instr} R{dest_val} <- {pinstr.result} (фиксация)")
            return
        if instr in {"JMP", "JZ", "JNZ"}:
            if debug:
                print(f"[WB @{addr}] {instr} (фиксация не требуется)")
            return
        raise ValueError(f"Неизвестная команда '{instr}' в WB")

    # ---------- Основной конвейерный цикл ----------
    def execute_pipelined(self, debug: bool = True) -> bool:
        """
        Конвейерное выполнение с поддержкой многотактных операций (уровень C) в конвейерном режиме (IF‑ID‑EX‑MEM‑WB)
        с RAW‑задержками и очисткой конвейера при переходах..
        """
        if not self.instructions:
            print("Ошибка: Программа не загружена")
            return False

        # Сброс состояния
        self.pc = 0
        self.running = True
        self.z_flag = False
        self.registers = [0] * len(self.registers)
        self.memory = [0] * len(self.memory)
        self.cycle_count = 0
        self.commit_count = 0
        self.data_stalls = 0
        self.control_flushes = 0
        self.ex_stalls = 0
        self.error = False

        pipeline: List[Optional[PipelineInstruction]] = [None] * 5
        max_cycles = 10000
        if debug:
            print("\n=== Конвейерное выполнение (5 стадий, многотактные MUL/DIV/MOD) ===")

        while self.cycle_count < max_cycles:
            self.cycle_count += 1
            if debug:
                print(f"\n--- Такт {self.cycle_count} ---")

            # 1) Разрешение переходов на стадии EX
            flush = False
            ex_instr = pipeline[2]
            if ex_instr and ex_instr.is_branch and self.running:
                taken = False
                if ex_instr.instr == "JMP":
                    taken = True
                elif ex_instr.instr == "JZ":
                    taken = self.z_flag
                elif ex_instr.instr == "JNZ":
                    taken = not self.z_flag
                if taken:
                    if ex_instr.branch_target is None:
                        raise ValueError("Не задан адрес перехода в branch_target")
                    self.pc = ex_instr.branch_target
                    flush = True
                    self.control_flushes += 1
                    if debug:
                        print(f"[EX @{ex_instr.addr}] {ex_instr.instr} -> переход на {self.pc}, flush IF/ID")
                else:
                    if debug:
                        print(f"[EX @{ex_instr.addr}] {ex_instr.instr} условие не выполнено")

            # 2) WB (фиксация результата)
            wb_instr = pipeline[4]
            if wb_instr is not None and self.running:
                try:
                    self._commit_instruction(wb_instr, debug=debug)
                    self.commit_count += 1
                    # print (wb_instr)
                except Exception as e:
                    print(f"Ошибка на стадии WB (адрес {wb_instr.addr}): {e}")
                    self.running = False

            # 3) Обнаружение RAW‑конфликтов: ID vs EX/MEM/WB
            stall_id = False
            id_instr = pipeline[1]
            if id_instr is not None and self.running:
                for older in pipeline[2:5]:
                    if older is None:
                        continue
                    if id_instr.reads & older.writes:
                        stall_id = True
                        self.data_stalls += 1
                        if debug:
                            print(f"[ID @{id_instr.addr}] RAW‑конфликт с @{older.addr}, stall")
                        break

            # 4) Определение занятости EX (многотактная операция)
            ex_busy = (pipeline[2] is not None and pipeline[2].ex_remaining_cycles > 0)
            if ex_busy:
                # Если EX занята, следующая инструкция не может войти в EX
                self.ex_stalls += 1

            # 5) Продвижение по стадиям (справа налево)
            new_pipeline: List[Optional[PipelineInstruction]] = [None] * 5

            # MEM -> WB
            if pipeline[3] is not None:
                instr_mem = pipeline[3]
                instr_mem.stage = "WB"
                new_pipeline[4] = instr_mem

            # EX -> MEM (только если EX инструкция завершила выполнение)
            if pipeline[2] is not None and self.running:
                instr_ex = pipeline[2]
                if instr_ex.ex_remaining_cycles == 0:
                    # Инструкция готова к переходу в MEM
                    instr_ex.stage = "MEM"
                    if instr_ex.instr == "MOV":
                        dest_type, dest_val = self.parse_operand(instr_ex.operands[0])
                        src_type, src_val = self.parse_operand(instr_ex.operands[1])
                        if src_type == "mem":
                            instr_ex.result = self.memory[src_val]
                            if debug:
                                print(f"[MEM @{instr_ex.addr}] MOV загрузка [{src_val}] -> {instr_ex.result}")
                        elif dest_type == "mem":
                            self.memory[dest_val] = instr_ex.result
                            if debug:
                                print(f"[MEM @{instr_ex.addr}] MOV запись [{dest_val}] <- {instr_ex.result}")
                    new_pipeline[3] = instr_ex
                else:
                    # Инструкция ещё не завершила выполнение, остаётся в EX
                    instr_ex.ex_remaining_cycles -= 1
                    instr_ex.stage = "EX"
                    new_pipeline[2] = instr_ex
                    if debug:
                        print(f"[EX @{instr_ex.addr}] {instr_ex.instr} осталось тактов: {instr_ex.ex_remaining_cycles}")

            # ID -> EX (только если EX свободна и нет stall_id)
            if not stall_id and not ex_busy and id_instr is not None and self.running:
                id_instr.stage = "EX"
                self.error = not self._execute_stage_ex(id_instr, debug)
                new_pipeline[2] = id_instr
            else:
                # Если EX занята или stall, то в EX остаётся то, что уже было (или пусто)
                if pipeline[2] is not None and pipeline[2].ex_remaining_cycles > 0:
                    # уже обработали выше, но если new_pipeline[2] ещё не установлен, копируем
                    if new_pipeline[2] is None:
                        # может случиться, если pipeline[2] не был перемещён в MEM, но и не попал в new_pipeline
                        # (например, когда stall и ex_busy)
                        # Копируем текущую инструкцию EX с уменьшенным счётчиком
                        instr_ex = pipeline[2]
                        instr_ex.ex_remaining_cycles -= 1
                        instr_ex.stage = "EX"
                        new_pipeline[2] = instr_ex
                        if debug:
                            print(f"[EX @{instr_ex.addr}] {instr_ex.instr} осталось тактов: {instr_ex.ex_remaining_cycles}")

            # IF -> ID (если нет flush и stall_id и EX не занята? ID может принимать новую инструкцию независимо от EX, если ID свободен)
            # Но если stall_id, то ID не продвигается.
            if not flush and not stall_id and pipeline[0] is not None and self.running and not ex_busy:
                instr_if = pipeline[0]
                instr_if.stage = "ID"
                new_pipeline[1] = instr_if
            else:
                # Если stall или flush, ID остаётся пустым (или сохраняем текущий? но flush очищает)
                if flush:
                    new_pipeline[1] = None
                else:
                    new_pipeline[1] = pipeline[1]  # сохраняем старую ID, если stall (но stall_id уже обработан)

            # 6) Новая выборка IF (если не flush, не останов, и есть код)
            if not flush and self.running and self.pc < len(self.instructions) and not stall_id and self.running:
                addr, instr, operands = self.instructions[self.pc]
                try:
                    fetched = self._analyze_instruction(addr, instr, operands)
                except Exception as e:
                    print(f"Ошибка анализа инструкции @{addr}: {e}")
                    self.running = False
                    fetched = None
                if fetched is not None:
                    if debug:
                        print(f"[IF @{addr}] {instr} {' '.join(operands)}")
                    new_pipeline[0] = fetched
                    self.pc += 1
            else:
                new_pipeline[0] = pipeline[0]

            # Если был flush, очищаем IF и ID (и EX? EX может содержать переход, который уже учтён)
            if flush:
                new_pipeline[0] = None
                new_pipeline[1] = None
                new_pipeline[2] = None

            pipeline = new_pipeline

            # Отладочный вывод
            if debug:
                names = ["IF", "ID", "EX", "MEM", "WB"]
                for idx, st in enumerate(names):
                    p_instr = pipeline[idx]
                    if p_instr is None:
                        desc = "-"
                    else:
                        desc = f"@{p_instr.addr}:{p_instr.instr}"
                    print(f"  {st:3}: {desc}")

            # Условие завершения
            if (not self.running) or all(p is None for p in pipeline):
                break

        if self.cycle_count >= max_cycles:
            print("Ошибка: превышен лимит тактов (возможно зацикливание)")
            return False

        if self.error:
            return False

        # Финальная статистика
        print("\n=== Статистика конвейера (уровень C) ===")
        print(f"Тактов всего:        {self.cycle_count}")
        print(f"Выполнено инструкций:{self.commit_count}")
        if self.commit_count > 0:
            cpi = self.cycle_count / self.commit_count
            print(f"CPI:                 {cpi:.3f}")
        print(f"Stall по данным RAW: {self.data_stalls}")
        print(f"Flush по переходам:  {self.control_flushes}")
        print(f"Stall из-за занятости EX (многотактные): {self.ex_stalls}")
        return True

def main(filename: str = "program.txt", mode: str = "seq"):
    """
    Точка входа для лабораторной работы 2, вариант 9.
    Режимы:
    - последовательный (референсный) – как в interpreter.py;
    - конвейерный – через PipelineSimulator.execute_pipelined.
    По умолчанию при запуске без аргументов выполняется:
      файл: program.txt
      режим: pipe (конвейерный).
    Можно переопределить:
      python lab2_variant9_pipeline.py program.txt seq
      python lab2_variant9_pipeline.py program.txt pipe
    """
    debug = True
    if len(sys.argv) >= 2:
        filename = sys.argv[1]
    if len(sys.argv) >= 3:
        mode = sys.argv[2].lower()

    asm = PipelineSimulator()
    print(f"Загрузка программы из файла: {filename}")
    if not asm.load_program(filename):
        return
    print(f"Загружено строк: {len(asm.lines)}")
    print("Первый проход: сбор меток и проверка синтаксиса...")
    if not asm.first_pass():
        print("Ошибка компиляции: обнаружены синтаксические ошибки")
        return
    print(f"Найдено меток: {len(asm.labels)}")
    print("Второй проход: формирование внутреннего представления...")
    if not asm.second_pass():
        print("Ошибка при формировании внутреннего представления")
        return
    print(f"Сформировано инструкций: {len(asm.instructions)}")

    if mode == "seq":
        result = asm.execute_with_stats(debug)
    elif mode == "pipe":
        result = asm.execute_pipelined(debug)
    else:
        print("Неизвестный режим. Используйте 'seq' или 'pipe'.")
        return

    if result:
        print("\nПрограмма выполнена успешно!")
        asm.print_state()
    else:
        print("\nОшибка выполнения программы")

if __name__ == "__main__":
    main()