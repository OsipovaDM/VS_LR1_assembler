import sys
from typing import List, Dict, Optional, Tuple, Set, Union

# ------------------------------------------------------------
# Конфигурация архитектуры
# ------------------------------------------------------------
MAX_CYCLES = 50
NON_MEM_WB = ("NOP", "HLT")  # Операции без доступа к памяти и записи данных

NUM_REGS = 8
MEM_SIZE = 256
REG_NAMES = [f"R{i}" for i in range(NUM_REGS)]

# Спецификация инструкций: мнемоника -> (кол-во операндов, список типов операндов)
# Типы: 'REG' - регистр R0-R7, 'IMM' - непосредственное число, 'ADDR' - прямой адрес памяти,
#       'MEM_REG' - [Rreg], 'LABEL' - метка, 'ANY' - любой допустимый операнд
INSTRUCTION_VARIANTS = {
    "HLT": [(0, [])],
    "NOP": [(0, [])],
    "JMP": [(1, ['LABEL'])],
    "MOV": [
        (2, ['REG', 'REG']),
        (2, ['REG', 'IMM']),
        (2, ['REG', 'MEM']),
        (2, ['REG', 'REG_IND']),
        (2, ['MEM', 'REG']),
        (2, ['REG_IND', 'REG']),
    ],
}


# ------------------------------------------------------------
# Парсинг операндов
# ------------------------------------------------------------
def parse_operand(token: str) -> Tuple[str, Union[int, str]]:
    """
    Парсинг операнда.
    Возвращает кортеж (тип, значение):
    - ('REG', номер_регистра) для R0-R7
    - ('IMM', число) для констант (положительные десятичные)
    - ('MEM', адрес) для [адрес]
    - ('REG_IND', номер_регистра) для [Rreg]
    - ('LABEL', имя_метки) для меток
    """
    token = token.upper()
    
    # Проверка на косвенную адресацию [addr] или [Rreg]
    if token.startswith('[') and token.endswith(']'):
        inner = token[1:-1]
        if inner.startswith('R') and inner[1:].isdigit():
            reg = int(inner[1:])
            if 0 <= reg < NUM_REGS:
                return ('REG_IND', reg)
            raise ValueError(f"Недопустимый регистр {inner}")
        if inner.isdigit():
            addr = int(inner)
            if 0 <= addr < MEM_SIZE:
                return ('MEM', addr)
            raise ValueError(f"Адрес памяти {addr} вне диапазона (0-{MEM_SIZE-1})")
        raise ValueError(f"Неверный адрес памяти: {inner}")

    # Проверка на прямой регистр
    if token.startswith('R') and token[1:].isdigit():
        reg = int(token[1:])
        if 0 <= reg < NUM_REGS:
            return ('REG', reg)
        raise ValueError(f"Недопустимый регистр {token}")

    # Проверка на непосредственное число
    if token.isdigit():
        value = int(token)
        if 0 <= value <= 65535:
            return ('IMM', value)
        raise ValueError(f"Число {value} выходит за пределы 16 бит (0-65535)")

    # Всё остальное считаем меткой (идентификатор)
    if token and token[0].isalpha():
        return ('LABEL', token)
    raise ValueError(f"Неверный операнд: {token}")


# ------------------------------------------------------------
# Класс Instruction
# ------------------------------------------------------------
class Instruction:
    def __init__(self, opcode: str, operands: List[str]):
        self.opcode = opcode.upper()
        self.operands = operands  # список строк, например ["R1", "R2", "R3"] или ["10"]
        self.address = None  # адрес (индекс) в программе

    def __repr__(self):
        return f"{self.opcode} {' '.join(self.operands)}"

    def reads(self) -> Set[Tuple[str, Union[int, str]]]:
        """Возвращает множество читаемых архитектурных объектов."""
        if self.opcode == "MOV":
            src_type, src_val = parse_operand(self.operands[1])
            if src_type == 'REG':
                return {('REG', src_val)}
            elif src_type == 'MEM':
                return {('MEM', src_val)}
            elif src_type == 'REG_IND':
                # Читается регистр-адрес
                return {('REG', src_val)}
            # imm и label не читают архитектурное состояние
        # Для остальных инструкций можно добавить позже
        return set()

    def writes(self) -> Set[Tuple[str, Union[int, str]]]:
        """Возвращает множество записываемых архитектурных объектов."""
        if self.opcode == "MOV":
            dest_type, dest_val = parse_operand(self.operands[0])
            if dest_type == 'REG':
                return {('REG', dest_val)}
            elif dest_type == 'MEM':
                return {('MEM', dest_val)}
            elif dest_type == 'REG_IND':
                # Запись в память по адресу из регистра – записывается память,
                # но адрес зависит от регистра. Для упрощения будем считать,
                # что запись в любую память конфликтует с любым чтением памяти.
                return {('MEM', None)}
        return set()


# ------------------------------------------------------------
# Класс Program
# ------------------------------------------------------------
class Program:
    def __init__(self):
        self.instructions: List[Instruction] = []
        self.labels: Dict[str, int] = {}  # метка -> адрес инструкции

    def add_instruction(self, instr: Instruction) -> int:
        """Добавляет инструкцию, возвращает её адрес"""
        instr.address = len(self.instructions)
        self.instructions.append(instr)
        return instr.address

    def set_label(self, label: str, address: int):
        """Привязывает метку к адресу инструкции"""
        if label in self.labels:
            raise ValueError(f"Duplicate label: {label}")
        self.labels[label] = address

    def resolve_label(self, label: str) -> Optional[int]:
        """Возвращает адрес метки или None, если не найдена"""
        return self.labels.get(label, None)


# ------------------------------------------------------------
# Валидация инструкции
# ------------------------------------------------------------
def validate_instruction(opcode: str, operands: List[str], line_num: int) -> None:
    """Проверяет инструкцию: количество операндов и соответствие типам."""
    variants = INSTRUCTION_VARIANTS.get(opcode)
    if variants is None:
        raise ValueError(f"Line {line_num}: Unknown instruction '{opcode}'")

    # Получаем типы операндов, одновременно проверяя их корректность
    op_types = []
    for operand in operands:
        try:
            typ, _ = parse_operand(operand)
            op_types.append(typ)
        except Exception as e:
            raise ValueError(f"Line {line_num}: Invalid operand '{operand}': {e}")

    # Ищем подходящий вариант
    for expected_count, expected_types in variants:
        if len(operands) != expected_count:
            continue
        if all(exp == typ for exp, typ in zip(expected_types, op_types)):
            return  # совпадение найдено

    raise ValueError(
        f"Line {line_num}: Instruction {opcode} does not accept operands: {' '.join(operands)}"
    )


# ------------------------------------------------------------
# Парсер
# ------------------------------------------------------------
def parse_program(filename: str) -> Program:
    program = Program()
    pending_label = None
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line_num, raw_line in enumerate(lines, start=1):
        # Удаляем комментарии (поддерживаем #)
        line = raw_line.split('#')[0].strip()
        if not line:
            continue

        # Проверка на метку
        if line.endswith(':'):
            label = line[:-1].strip()
            if not label:
                raise ValueError(f"Line {line_num}: Empty label")
            if ' ' in label:
                raise ValueError(f"Line {line_num}: Label '{label}' contains spaces")
            if pending_label is not None:
                # несколько меток подряд – последняя перезаписывает, но все указывают на следующую инструкцию
                pass
            pending_label = label
            continue
        elif ':' in line:
            # Если есть двоеточие не в конце, значит строка содержит метку и инструкцию – ошибка
            raise ValueError(f"Line {line_num}: Invalid line '{line}' (label must be alone on a line)")

        # Это инструкция
        tokens = line.split()
        opcode = tokens[0].upper()
        operands = tokens[1:] if len(tokens) > 1 else []

        # Валидация инструкции
        validate_instruction(opcode, operands, line_num)

        instr = Instruction(opcode, operands)
        address = program.add_instruction(instr)
        if pending_label is not None:
            program.set_label(pending_label, address)
            pending_label = None

    if pending_label is not None:
        # Метка в конце файла без инструкции
        raise ValueError(f"Label {pending_label} without following instruction (end of file)")

    return program


# ------------------------------------------------------------
# Состояние системы (регистры, память, флаги)
# ------------------------------------------------------------
class State:
    def __init__(self, mem_size=MEM_SIZE, num_regs=NUM_REGS):
        self.pc = 0
        self.regs = [0] * num_regs
        self.mem = [0] * mem_size
        self.z = False  # флаг нуля

    def read_reg(self, reg_name: str) -> int:
        """Читает значение регистра. reg_name: R0..R7"""
        idx = int(reg_name[1:])
        return self.regs[idx]

    def write_reg(self, reg_name: str, value: int):
        idx = int(reg_name[1:])
        self.regs[idx] = value

    def read_mem(self, addr: int) -> int:
        if 0 <= addr < len(self.mem):
            return self.mem[addr]
        else:
            raise ValueError(f"Memory address out of range: {addr}")

    def write_mem(self, addr: int, value: int):
        if 0 <= addr < len(self.mem):
            self.mem[addr] = value
        else:
            raise ValueError(f"Memory address out of range: {addr}")

    def set_z(self, value: int):
        """Устанавливает флаг Z в зависимости от значения (0 -> True)"""
        self.z = (value == 0)

    def copy(self):
        """Создает глубокую копию состояния (для отладки)"""
        new_state = State(len(self.mem), len(self.regs))
        new_state.pc = self.pc
        new_state.regs = self.regs[:]
        new_state.mem = self.mem[:]
        new_state.z = self.z
        return new_state

    def __repr__(self):
        return f"PC={self.pc} Z={self.z} REGS={self.regs} MEM={self.mem[:10]}..."  # кратко


# ------------------------------------------------------------
# Базовый класс исполнителя
# ------------------------------------------------------------
class BaseExecutor:
    def __init__(self, program: Program, state: State, debug: bool = False):
        self.program = program
        self.state = state
        self.debug = debug
        self.halted = False
        self.instructions_executed = 0

    def run(self):
        raise NotImplementedError

    def get_stats(self):
        raise NotImplementedError


# ------------------------------------------------------------
# Последовательный исполнитель (пока заглушка)
# ------------------------------------------------------------
class SequentialExecutor(BaseExecutor):
    def run(self):
        # Для простоты можно реализовать позже, но для задания требуется только конвейер с MOV
        pass

    def get_stats(self):
        return {}


# ------------------------------------------------------------
# Конвейерный исполнитель (уровень C: многотактные операции)
# ------------------------------------------------------------
class PipelineStage:
    """Представляет одну стадию конвейера"""
    def __init__(self):
        self.instr: Optional[Instruction] = None
        # Дополнительные поля для передачи данных между стадиями
        self.result: Optional[int] = None          # результат (вычисленный или из памяти)
        self.dest_type: Optional[str] = None       # тип приёмника ('REG', 'MEM', 'REG_IND')
        self.dest_val: Optional[Union[int, str]] = None  # номер регистра или адрес
        self.src_type: Optional[str] = None        # тип источника ('REG', 'IMM', 'MEM', 'REG_IND')
        self.src_val: Optional[Union[int, str]] = None   # значение источника
        self.remaining_cycles: int = 0             # для многотактных операций (MUL/DIV)
        self.pc_target: Optional[int] = None       # целевой адрес для перехода
        self.extra: Dict = {}                      # дополнительные данные (типы операндов и т.п.)


class PipelineExecutor(BaseExecutor):
    def __init__(self, program: Program, state: State, debug: bool = False):
        super().__init__(program, state, debug)

        # Стадии
        self.if_stage = PipelineStage()
        self.id_stage = PipelineStage()
        self.ex_stage = PipelineStage()
        self.mem_stage = PipelineStage()
        self.wb_stage = PipelineStage()

        # Счётчики и статистика
        self.cycles = 0
        self.instructions_committed = 0
        self.stall_cycles_data = 0
        self.stall_cycles_struct = 0
        self.flush_cycles = 0

        self.stall_pipeline = False

    def check_data_hazard(self, instr: Instruction) -> bool:
        """
        Проверяет, конфликтует ли инструкция по данным с инструкциями в EX и MEM.
        Возвращает True, если нужно stall.
        """
        reads = instr.reads()
        # Конфликт с EX
        if self.ex_stage.instr:
            writes_ex = self.ex_stage.instr.writes()
            if reads & writes_ex:
                return True
        # Конфликт с MEM
        if self.mem_stage.instr:
            writes_mem = self.mem_stage.instr.writes()
            if reads & writes_mem:
                return True
        return False

    def flush(self, stages: List[str]):
        """Очистка указанных стадий"""
        if 'IF' in stages: self.if_stage = PipelineStage()
        if 'ID' in stages: self.id_stage = PipelineStage()
        if 'EX' in stages: self.ex_stage = PipelineStage()
        if 'MEM' in stages: self.mem_stage = PipelineStage()
        if 'WB' in stages: self.wb_stage = PipelineStage()
        self.flush_cycles += 1

    def has_hlt_in_pipeline(self) -> bool:
        """Проверяет, есть ли HLT в любой стадии конвейера, кроме IF (так как IF может только что выбрать HLT)."""
        return (self.id_stage.instr and self.id_stage.instr.opcode == "HLT") or \
            (self.ex_stage.instr and self.ex_stage.instr.opcode == "HLT") or \
            (self.mem_stage.instr and self.mem_stage.instr.opcode == "HLT") or \
            (self.wb_stage.instr and self.wb_stage.instr.opcode == "HLT")

    def fetch(self):
        """Стадия IF: выборка инструкции по PC"""
        if self.if_stage.instr is not None:  # stall
            return
        if self.halted:
            return
        if self.state.pc < 0 or self.state.pc >= len(self.program.instructions):
            if self.has_hlt_in_pipeline():
                return
            raise RuntimeError("PC out of bounds")
        instr = self.program.instructions[self.state.pc]
        self.if_stage.instr = instr
        self.state.pc += 1

    def decode(self):
        """Стадия ID: декодирование, чтение операндов, обнаружение конфликтов"""
        # Продвижение из IF в ID, если не stall
        if self.id_stage.instr is None:
            self.id_stage = self.if_stage
            self.if_stage = PipelineStage()

        if self.id_stage.instr is None:
            return

        # Проверка hazard
        if self.check_data_hazard(self.id_stage.instr):
            self.stall_cycles_data += 1
            self.stall_pipeline = True
        else:
            self.stall_pipeline = False

    def execute(self):
        """Стадия EX: выполнение (возможно, многотактное)"""
        # Продвижение из ID в EX, если не stall
        if self.stall_pipeline:
            return

        self.ex_stage = self.id_stage
        self.id_stage = PipelineStage()

        if self.ex_stage.instr is None:
            return

        instr = self.ex_stage.instr
        opcode = instr.opcode

        # Определяем количество тактов для выполнения (для MUL/DIV многотактность)
        if opcode in ['MUL', 'DIV']:
            self.ex_stage.remaining_cycles = 3
        else:
            self.ex_stage.remaining_cycles = 1

        if opcode == "HLT":
            self.halted = True
        elif opcode == "JMP":
            op = instr.operands[0]
            try:
                target = int(op)
            except ValueError:
                target = self.program.resolve_label(op)
                if target is None:
                    raise RuntimeError(f"Undefined label '{op}' for JMP")
            self.ex_stage.pc_target = target
        elif opcode == "MOV":
            dest_operand = instr.operands[0]
            src_operand = instr.operands[1]
            dest_type, dest_val = parse_operand(dest_operand)
            src_type, src_val = parse_operand(src_operand)

            # Сохраняем типы и значения
            self.ex_stage.dest_type = dest_type
            self.ex_stage.dest_val = dest_val
            self.ex_stage.src_type = src_type
            self.ex_stage.src_val = src_val

            # Вычисляем результат, если он известен сразу
            if src_type == 'REG':
                self.ex_stage.result = self.state.read_reg(f"R{src_val}")
            elif src_type == 'IMM':
                self.ex_stage.result = src_val
            # Для MEM и REG_IND результат будет получен на стадии MEM
            elif src_type in ('MEM', 'REG_IND'):
                self.ex_stage.result = None
            else:
                raise RuntimeError(f"MOV: unsupported source type {src_type}")

    def memory(self):
        """Стадия MEM: доступ к памяти (чтение/запись)"""
        if self.ex_stage.instr is None:
            return
        if self.ex_stage.remaining_cycles > 0:
            return

        self.mem_stage = self.ex_stage
        self.ex_stage = PipelineStage()

        if self.mem_stage.instr is None:
            return

        instr = self.mem_stage.instr
        if instr.opcode != "MOV":
            return

        dest_type = self.mem_stage.dest_type
        src_type = self.mem_stage.src_type
        dest_val = self.mem_stage.dest_val
        src_val = self.mem_stage.src_val

        # Обработка загрузки из памяти
        if src_type == 'MEM':
            addr = src_val
            self.mem_stage.result = self.state.read_mem(addr)
        elif src_type == 'REG_IND':
            addr = self.state.read_reg(f"R{src_val}")
            self.mem_stage.result = self.state.read_mem(addr)

        # Обработка записи в память
        if dest_type == 'MEM':
            addr = dest_val
            value = self.mem_stage.result
            # Если результат ещё не вычислен (например, когда источник тоже память)
            if value is None:
                # В нашем случае значение для записи должно быть уже в result, иначе ошибка
                raise RuntimeError("MOV: запись в память без значения")
            self.state.write_mem(addr, value)
        elif dest_type == 'REG_IND':
            addr = self.state.read_reg(f"R{dest_val}")
            value = self.mem_stage.result
            if value is None:
                raise RuntimeError("MOV: запись в память без значения")
            self.state.write_mem(addr, value)

    def writeback(self):
        """Стадия WB: запись результата в регистр"""
        # Продвижение из MEM в WB
        self.wb_stage = self.mem_stage
        self.mem_stage = PipelineStage()

        if self.wb_stage.instr is None:
            return

        instr = self.wb_stage.instr
        if instr.opcode == "MOV":
            if self.wb_stage.dest_type == 'REG':
                value = self.wb_stage.result
                if value is None:
                    raise RuntimeError("MOV: result is None in WB")
                self.state.write_reg(f"R{self.wb_stage.dest_val}", value)

        self.instructions_committed += 1

    def tick(self):
        """Один такт конвейера"""
        if self.debug and self.cycles > 0:
            self.debug_print()

        # Обработка перехода (после того как стадии выполнены)
        if self.ex_stage.pc_target is not None:
            self.state.pc = self.ex_stage.pc_target
            self.flush(['IF', 'ID'])
            self.ex_stage.pc_target = None

        # Обновление многотактных операций в EX
        if self.ex_stage.instr:
            if self.ex_stage.remaining_cycles > 0:
                self.ex_stage.remaining_cycles -= 1
                # Если операция завершилась, выполняем её (результат вычисляем)
                if self.ex_stage.remaining_cycles == 0:
                    # Здесь можно добавить выполнение MUL/DIV, если потребуется
                    pass

        # Продвижение по стадиям (обратный порядок)
        self.writeback()
        self.memory()
        self.execute()
        self.decode()
        self.fetch()

        self.cycles += 1

    def debug_print(self):
        print(f"Cycle {self.cycles}:")
        print(f"  IF: {self.if_stage.instr}")
        print(f"  ID: {self.id_stage.instr} (stall={self.stall_pipeline})")
        print(f"  EX: {self.ex_stage.instr} (rem={self.ex_stage.remaining_cycles})")
        print(f"  MEM:{self.mem_stage.instr}")
        print(f"  WB: {self.wb_stage.instr}")
        print(f"  State: PC={self.state.pc}, Z={self.state.z}, REGS={self.state.regs}")

    def run(self):
        """Запуск конвейера до остановки"""
        while not self.halted:
            self.tick()
            if self.cycles > MAX_CYCLES:
                raise RuntimeError("Too many cycles")
        self.drain()

    def drain(self):
        """Дренаж конвейера: дождаться, пока все инструкции дойдут до WB"""
        while (self.if_stage.instr is not None or
               self.id_stage.instr is not None or
               self.ex_stage.instr is not None or
               self.mem_stage.instr is not None or
               self.wb_stage.instr is not None):
            self.tick()
            if self.cycles > MAX_CYCLES:
                raise RuntimeError("Drain timeout")

    def get_stats(self):
        return {
            "cycles": self.cycles,
            "instructions_committed": self.instructions_committed,
            "CPI": self.cycles / self.instructions_committed if self.instructions_committed else 0,
            "stall_data": self.stall_cycles_data,
            "stall_struct": self.stall_cycles_struct,
            "flush": self.flush_cycles,
        }


# ------------------------------------------------------------
# Точка входа с аргументами командной строки
# ------------------------------------------------------------
def main(file: str = "program.txt", debug: bool = True, mode: str = "pipe"):
    """
    Главная функция интерпретатора.
    :param file: путь к файлу с программой на псевдо-ассемблере
    :param debug: флаг отладочного вывода
    :param mode: режим выполнения ("seq" или "pipe")
    """
    try:
        program = parse_program(file)
    except FileNotFoundError:
        print(f"Error: File '{file}' not found.")
        return
    except Exception as e:
        print(f"Error parsing program: {e}")
        return

    print("Program loaded:")
    # Вывод загруженной программы без комментариев, с метками привязанными к инструкциям
    for i, instr in enumerate(program.instructions):
        labels = [lbl for lbl, addr in program.labels.items() if addr == i]
        label_str = " ".join(f"{lbl}:" for lbl in labels)
        if label_str:
            print(f"  {i:3}: {label_str} {instr}")
        else:
            print(f"  {i:3}: {instr}")

    if mode == "seq":
        print("\n--- Sequential execution ---")
        state = State()
        executor = SequentialExecutor(program, state, debug)
        try:
            executor.run()
        except Exception as e:
            print(f"Error during execution: {e}")
        print(f"Final state: {state}")
        stats = executor.get_stats()
        print(f"Stats: {stats}")
    else:
        print("\n--- Pipelined execution ---")
        state = State()
        executor = PipelineExecutor(program, state, debug)
        try:
            executor.run()
        except Exception as e:
            print(f"Error during execution: {e}")
        print(f"Final state: {state}")
        stats = executor.get_stats()
        print(f"Stats: {stats}")


if __name__ == "__main__":
    main()