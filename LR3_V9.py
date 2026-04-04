import sys
from typing import List, Dict, Optional, Tuple, Set, Union
# ------------------------------------------------------------
# Конфигурация архитектуры
# ------------------------------------------------------------
MAX_NUM = 0xFFFF
MAX_CYCLES = 1000          # максимальное количество тактов до принудительной остановки
NUM_REGS = 8               # количество регистров общего назначения (R0..R7)
MEM_SIZE = 256             # размер памяти данных в байтах
STACK_START = 255          # начальное значение указателя стека (вершина стека)
# Словарь допустимых вариантов инструкций.
# Ключ – мнемоника, значение – список кортежей (количество операндов, список ожидаемых типов).
# Типы операндов: REG, IMM, MEM, REG_IND, LABEL.
INSTRUCTION_VARIANTS = {
    "HLT": [(0, [])],
    "NOP": [(0, [])],
    "JMP": [(1, ['LABEL'])],
    "JZ":  [(1, ['LABEL'])],
    "JNZ": [(1, ['LABEL'])],
    "CALL": [(1, ['LABEL'])],
    "RETI": [(0, [])],
    "MOV": [
        (2, ['REG', 'REG']),
        (2, ['REG', 'IMM']),
        (2, ['REG', 'MEM']),
        (2, ['REG', 'REG_IND']),
        (2, ['MEM', 'REG']),
        (2, ['MEM', 'IMM']),
        (2, ['REG_IND', 'REG']),
        (2, ['REG_IND', 'IMM']),
    ],
    "CMP": [(2, ['REG', 'REG'])],
    "ADD": [(3, ['REG', 'REG', 'REG'])],
    "SUB": [(3, ['REG', 'REG', 'REG'])],
    "MUL": [(3, ['REG', 'REG', 'REG'])],
    "DIV": [(3, ['REG', 'REG', 'REG'])],
    "MOD": [(3, ['REG', 'REG', 'REG'])],
}
# ------------------------------------------------------------
# Парсинг операндов
# ------------------------------------------------------------
def parse_operand(token: str) -> Tuple[str, Union[int, str]]:
    """
    Преобразует текстовое представление операнда в типизированное значение.
    Поддерживаемые форматы:
      - R0..R7                → ('REG', номер_регистра)
      - [число]               → ('MEM', адрес)
      - [Rрегистр]            → ('REG_IND', номер_регистра)
      - целое число           → ('IMM', значение)
      - слово (идентификатор) → ('LABEL', имя_метки)
    В случае ошибки генерирует ValueError.
    """
    token = token.upper()
    # Косвенная адресация: [что-то]
    if token.startswith('[') and token.endswith(']'):
        inner = token[1:-1]
        # [Rreg]
        if inner.startswith('R') and inner[1:].isdigit():
            reg = int(inner[1:])
            if 0 <= reg < NUM_REGS:
                return ('REG_IND', reg)
            raise ValueError(f"Недопустимый регистр {inner}")
        # [адрес]
        if inner.isdigit():
            addr = int(inner)
            if 0 <= addr < MEM_SIZE:
                return ('MEM', addr)
            raise ValueError(f"Адрес памяти {addr} вне диапазона (0-{MEM_SIZE-1})")
        raise ValueError(f"Неверный адрес памяти: {inner}")
    # Прямой регистр
    if token.startswith('R') and token[1:].isdigit():
        reg = int(token[1:])
        if 0 <= reg < NUM_REGS:
            return ('REG', reg)
        raise ValueError(f"Недопустимый регистр {token}")
    # Непосредственное значение (только положительные десятичные числа, 0-65535)
    if token.isdigit():
        value = int(token)
        if 0 <= value <= 65535:
            return ('IMM', value)
        raise ValueError(f"Число {value} выходит за пределы 16 бит (0-65535)")
    # Метка (идентификатор, начинающийся с буквы)
    if token and token[0].isalpha():
        return ('LABEL', token)
    raise ValueError(f"Неверный операнд: {token}")
# ------------------------------------------------------------
# Класс Instruction – представление одной инструкции
# ------------------------------------------------------------
class Instruction:
    """
    Класс, инкапсулирующий информацию об одной инструкции псевдо-ассемблера.
    Хранит мнемонику, список операндов (строки) и адрес в программе.
    Предоставляет методы для получения множеств читаемых и записываемых
    архитектурных объектов (используются для обнаружения RAW-зависимостей).
    """
    def __init__(self, opcode: str, operands: List[str]):
        self.opcode = opcode.upper()          # мнемоника в верхнем регистре
        self.operands = operands              # исходные строки операндов
        self.address = None                   # номер инструкции в программе (устанавливается при добавлении)
    def __repr__(self):
        return f"{self.opcode} {' '.join(self.operands)}"
    def reads(self) -> Set[Tuple[str, Union[int, str]]]:
        """
        Возвращает множество архитектурных объектов, которые инструкция читает.
        Каждый объект представляется кортежем (тип, идентификатор).
        Типы: 'REG', 'MEM', 'FLAG'.
        Для инструкций, не читающих состояние, возвращается пустое множество.
        """
        reads = set()
        op = self.opcode
        # Инструкции, не читающие архитектурное состояние
        if op in {"HLT", "NOP", "JMP", "CALL", "RETI"}:
            return reads
        # Условные переходы читают флаг Z
        if op in {"JZ", "JNZ"}:
            reads.add(('FLAG', 'Z'))
            return reads
        # Для остальных инструкций: все операнды, кроме первого, являются источниками.
        # Исключение: CMP – оба операнда источники.
        for i, operand in enumerate(self.operands):
            if i == 0 and op != "CMP":
                continue
            try:
                typ, val = parse_operand(operand)
                if typ == 'REG':
                    reads.add(('REG', val))
                elif typ == 'MEM':
                    reads.add(('MEM', val))
                elif typ == 'REG_IND':
                    # Чтение из памяти по адресу в регистре – сам регистр читается
                    reads.add(('REG', val))
            except Exception:
                # Если операнд некорректен, он уже должен был отсеяться на этапе валидации,
                # но на всякий случай игнорируем ошибку.
                continue
        return reads
    def writes(self) -> Set[Tuple[str, Union[int, str]]]:
        """
        Возвращает множество архитектурных объектов, которые инструкция записывает.
        Каждый объект представляется кортежем (тип, идентификатор).
        Типы: 'REG', 'MEM', 'FLAG'.
        Для инструкций, не меняющих состояние, возвращается пустое множество.
        """
        writes = set()
        op = self.opcode
        # Инструкции, не изменяющие архитектурное состояние
        if op in {"HLT", "NOP", "JMP", "JZ", "JNZ", "CALL", "RETI"}:
            return writes
        # CMP устанавливает только флаг Z
        if op == "CMP":
            writes.add(('FLAG', 'Z'))
            return writes
        # MOV и арифметические операции: первый операнд – приёмник
        if self.operands:
            try:
                dest_type, dest_val = parse_operand(self.operands[0])
                if dest_type == 'REG':
                    writes.add(('REG', dest_val))
                elif dest_type == 'MEM':
                    writes.add(('MEM', dest_val))
                elif dest_type == 'REG_IND':
                    # Косвенная запись в память – адрес зависит от регистра,
                    # поэтому конфликт с любой памятью моделируется через ('MEM', None)
                    writes.add(('MEM', None))
            except Exception:
                pass
        # Арифметические операции также изменяют флаг Z
        if op in {"ADD", "SUB", "MUL", "DIV", "MOD"}:
            writes.add(('FLAG', 'Z'))
        return writes
# ------------------------------------------------------------
# Класс Program – хранение списка инструкций и меток
# ------------------------------------------------------------
class Program:
    """
    Представляет загруженную программу: последовательность инструкций и
    соответствие между именами меток и адресами инструкций.
    """
    def __init__(self):
        self.instructions: List[Instruction] = []   # список инструкций в порядке следования
        self.labels: Dict[str, int] = {}            # метка -> адрес (индекс в instructions)
    def add_instruction(self, instr: Instruction) -> int:
        """Добавляет инструкцию в конец программы, возвращает её адрес."""
        instr.address = len(self.instructions)
        self.instructions.append(instr)
        return instr.address
    def set_label(self, label: str, address: int):
        """Привязывает метку к адресу. Генерирует ошибку, если метка уже существует."""
        if label in self.labels:
            raise ValueError(f"Duplicate label: {label}")
        self.labels[label] = address
    def resolve_label(self, label: str) -> Optional[int]:
        """Возвращает адрес, соответствующий метке, или None, если метка не определена."""
        return self.labels.get(label, None)
# ------------------------------------------------------------
# Валидация инструкции на основе INSTRUCTION_VARIANTS
# ------------------------------------------------------------
def validate_instruction(opcode: str, operands: List[str], line_num: int) -> None:
    """
    Проверяет, существует ли инструкция с таким opcode, и соответствуют ли
    типы операндов одному из разрешённых вариантов.
    В случае ошибки генерирует ValueError с указанием строки.
    """
    variants = INSTRUCTION_VARIANTS.get(opcode)
    if variants is None:
        raise ValueError(f"Line {line_num}: Unknown instruction '{opcode}'")
    # Получаем типы операндов, одновременно проверяя их корректность через parse_operand
    op_types = []
    for operand in operands:
        try:
            typ, _ = parse_operand(operand)
            op_types.append(typ)
        except Exception as e:
            raise ValueError(f"Line {line_num}: Invalid operand '{operand}': {e}")
    # Ищем вариант с подходящим количеством и типами операндов
    for expected_count, expected_types in variants:
        if len(operands) != expected_count:
            continue
        if all(exp == typ for exp, typ in zip(expected_types, op_types)):
            return  # совпадение найдено
    # Ни один вариант не подошёл
    raise ValueError(
        f"Line {line_num}: Instruction {opcode} does not accept operands: {' '.join(operands)}"
    )
# ------------------------------------------------------------
# Парсер программы из текстового файла
# ------------------------------------------------------------
def parse_program(filename: str) -> Program:
    """
    Читает файл с исходным кодом, удаляет комментарии (символ #),
    обрабатывает метки и инструкции, возвращает объект Program.
    """
    program = Program()
    pending_label = None      # метка, ожидающая следующую инструкцию
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    for line_num, raw_line in enumerate(lines, start=1):
        # Удаляем комментарии и лишние пробелы
        line = raw_line.split('#')[0].strip()
        if not line:
            continue
        # Если строка заканчивается двоеточием – это метка
        if line.endswith(':'):
            label = line[:-1].strip()
            if not label:
                raise ValueError(f"Line {line_num}: Empty label")
            if ' ' in label:
                raise ValueError(f"Line {line_num}: Label '{label}' contains spaces")
            pending_label = label   # запоминаем метку для следующей инструкции
            continue
        # Если двоеточие есть, но не в конце – ошибка (метка и инструкция в одной строке)
        if ':' in line:
            raise ValueError(f"Line {line_num}: Invalid line '{line}' (label must be alone on a line)")
        # Разбираем инструкцию
        tokens = line.split()
        opcode = tokens[0].upper()
        operands = tokens[1:] if len(tokens) > 1 else []
        # Валидация инструкции
        validate_instruction(opcode, operands, line_num)
        instr = Instruction(opcode, operands)
        address = program.add_instruction(instr)
        # Если была отложенная метка, привязываем её к текущему адресу
        if pending_label is not None:
            program.set_label(pending_label, address)
            pending_label = None
    # Если после всех строк осталась неиспользованная метка – ошибка
    if pending_label is not None:
        # Метка в конце файла без инструкции
        raise ValueError(f"Label {pending_label} without following instruction (end of file)")
    return program
# ------------------------------------------------------------
# Класс State – архитектурное состояние процессора
# ------------------------------------------------------------
class State:
    """
    Состояние вычислительной системы:
      - pc      – счётчик команд (номер следующей инструкции)
      - regs    – 8 регистров общего назначения (R0..R7)
      - mem     – линейная память данных размером MEM_SIZE
      - z       – флаг нуля (используется для условных переходов)
      - sp      – указатель стека (адрес вершины стека)
    """
    def __init__(self, mem_size=MEM_SIZE, num_regs=NUM_REGS):
        self.pc = 0
        self.regs = [0] * num_regs
        self.mem = [0] * mem_size
        self.z = False
        self.sp = STACK_START
    def read_reg(self, reg_num: int) -> int:
        """Возвращает значение регистра по номеру (0..7)."""
        if 0 <= reg_num < len(self.regs):
            return self.regs[reg_num]
        raise ValueError(f"Invalid register number: {reg_num}")
    def write_reg(self, reg_num: int, value: int):
        """Записывает значение в регистр."""
        if 0 <= reg_num < len(self.regs):
            self.regs[reg_num] = value
        else:
            raise ValueError(f"Invalid register number: {reg_num}")
    def read_mem(self, addr: int) -> int:
        """Читает байт из памяти по адресу (0..MEM_SIZE-1)."""
        if 0 <= addr < len(self.mem):
            return self.mem[addr]
        raise ValueError(f"Memory address out of range: {addr}")
    def write_mem(self, addr: int, value: int):
        """Записывает байт в память."""
        if 0 <= addr < len(self.mem):
            self.mem[addr] = value
        else:
            raise ValueError(f"Memory address out of range: {addr}")
    def set_z(self, value: int):
        """
        Устанавливает флаг Z на основе переданного значения.
        Если value != 0, то Z = False, иначе True.
        """
        self.z = (value != 0)
    def push(self, value: int):
        """Помещает значение в стек (уменьшает SP и записывает в память)."""
        if self.sp < 0:
            raise ValueError("Stack overflow")
        self.write_mem(self.sp, value)
        self.sp -= 1
    def pop(self) -> int:
        """Извлекает значение из стека (увеличивает SP и читает из памяти)."""
        self.sp += 1
        if self.sp > STACK_START:
            raise ValueError("Stack underflow")
        return self.read_mem(self.sp)
    def copy(self):
        """Создаёт глубокую копию состояния (используется для отладки)."""
        new_state = State(len(self.mem), len(self.regs))
        new_state.pc = self.pc
        new_state.regs = self.regs[:]
        new_state.mem = self.mem[:]
        new_state.z = self.z
        new_state.sp = self.sp
        return new_state
    def __repr__(self):
        return f"PC={self.pc} Z={self.z} SP={self.sp} REGS={self.regs} MEM={self.mem[:10]}..."
# ------------------------------------------------------------
# Базовый класс исполнителя (абстрактный)
# ------------------------------------------------------------
class BaseExecutor:
    """Абстрактный класс для исполнителей (последовательный/конвейерный)."""
    def __init__(self, program: Program, state: State, debug: bool = False):
        self.program = program          # загруженная программа
        self.state = state              # текущее состояние
        self.debug = debug              # флаг отладочного вывода
        self.halted = False             # признак остановки (HLT)
        self.instructions_committed = 0 # количество завершённых инструкций
    def run(self):
        """Запуск выполнения программы."""
        raise NotImplementedError
    def get_stats(self):
        """Возвращает словарь со статистикой выполнения."""
        raise NotImplementedError
# ------------------------------------------------------------
# Конвейерный исполнитель (5-стадийный конвейер)
# ------------------------------------------------------------
class PipelineStage:
    """
    Представляет одну стадию конвейера.
    Хранит инструкцию и все вспомогательные данные, передаваемые между стадиями.
    """
    def __init__(self):
        self.instr: Optional[Instruction] = None   # инструкция, находящаяся на этой стадии
        self.result: Optional[int] = None          # результат вычисления (EX) или прочитанное из памяти значение
        self.dest_type: Optional[str] = None       # тип приёмника для MOV (REG, MEM, REG_IND)
        self.dest_val: Optional[Union[int, str]] = None  # номер регистра или адрес
        self.src_type: Optional[str] = None        # тип источника для MOV
        self.src_val: Optional[Union[int, str]] = None   # значение источника
        self.remaining_cycles: int = 0             # оставшееся количество тактов на стадии EX (для MUL/DIV)
        self.pc_target: Optional[int] = None       # целевой адрес для перехода (JMP, JZ, JNZ, CALL, RETI)
        self.extra: Dict = {}                      # дополнительные данные (например, флаг Z для арифметики)
class PipelineExecutor(BaseExecutor):
    """
    Конвейерный исполнитель, поддерживающий как конвейерный, так и последовательный
    режим выполнения. В последовательном режиме (sequential=True) выборка следующей
    инструкции блокируется до завершения предыдущей (т.е. конвейер работает как
    простой последовательный интерпретатор).
    """
    def __init__(self, program: Program, state: State, debug: bool = False, sequential: bool = False):
        super().__init__(program, state, debug)
        self.sequential = sequential   # True – последовательный режим, False – конвейерный
        self.if_blocked = False        # флаг блокировки стадии IF (используется в последовательном режиме)
        # Пять стадий конвейера
        self.if_stage = PipelineStage()
        self.id_stage = PipelineStage()
        self.ex_stage = PipelineStage()
        self.mem_stage = PipelineStage()
        self.wb_stage = PipelineStage()
        # Статистика
        self.cycles = 0
        self.stall_cycles_data = 0
        self.stall_cycles_struct = 0
        self.flush_cycles = 0
        self.stall_pipeline = False   # признак того, что на текущем такте ID должна застопорить продвижение
    def check_data_hazard(self, instr: Instruction) -> bool:
        """
        Проверяет, существует ли RAW-зависимость между данной инструкцией (на стадии ID)
        и инструкциями, находящимися на стадиях EX или MEM.
        Возвращает True, если требуется stall.
        """
        reads = instr.reads()
        # Проверяем конфликт с инструкцией на стадии EX
        if self.ex_stage.instr:
            writes_ex = self.ex_stage.instr.writes()
            if reads & writes_ex:
                return True
        # Проверяем конфликт с инструкцией на стадии MEM
        if self.mem_stage.instr:
            writes_mem = self.mem_stage.instr.writes()
            if reads & writes_mem:
                return True
        return False
    def flush(self, stages: List[str]):
        """
        Очищает указанные стадии конвейера (создаёт новые пустые объекты PipelineStage).
        Увеличивает счётчик flush_cycles.
        """
        if 'IF' in stages:
            self.if_stage = PipelineStage()
        if 'ID' in stages:
            self.id_stage = PipelineStage()
        if 'EX' in stages:
            self.ex_stage = PipelineStage()
        if 'MEM' in stages:
            self.mem_stage = PipelineStage()
        if 'WB' in stages:
            self.wb_stage = PipelineStage()
        self.flush_cycles += 1
    def has_hlt_in_pipeline(self) -> bool:
        """Проверяет, находится ли инструкция HLT на любой из стадий, кроме IF."""
        for stage in (self.id_stage, self.ex_stage, self.mem_stage, self.wb_stage):
            if stage.instr and stage.instr.opcode == "HLT":
                return True
        return False
    # --------------------------------------------------------
    # Стадии конвейера
    # --------------------------------------------------------
    def fetch(self):
        """
        Стадия IF (Instruction Fetch).
        Выбирает следующую инструкцию по адресу PC, если конвейер не заблокирован
        и программа не остановлена. В последовательном режиме выборка происходит
        только если if_blocked == False (т.е. предыдущая инструкция уже завершилась).
        """
        if self.if_stage.instr is not None:
            return            # в IF уже есть инструкция – ждём продвижения
        if self.halted:
            return
        # В последовательном режиме блокируем выборку, пока не освободится
        if self.sequential and self.if_blocked:
            return
        if self.state.pc < 0 or self.state.pc >= len(self.program.instructions):
            # Если PC вышел за границы, но в конвейере есть HLT – нормальное завершение
            if self.has_hlt_in_pipeline():
                return
            raise RuntimeError("PC out of bounds")
        instr = self.program.instructions[self.state.pc]
        self.if_stage.instr = instr
        self.state.pc += 1
        if self.sequential:
            self.if_blocked = True   # блокируем выборку следующей инструкции
    def decode(self):
        """
        Стадия ID (Instruction Decode).
        Продвигает инструкцию из IF в ID. Если это конвейерный режим, проверяет
        RAW-зависимости и устанавливает stall_pipeline. В последовательном режиме
        stall никогда не требуется.
        """
        # Продвижение из IF в ID, если ID пуста
        if self.id_stage.instr is None:
            self.id_stage = self.if_stage
            self.if_stage = PipelineStage()
        if self.id_stage.instr is None:
            return
        if not self.sequential:
            if self.check_data_hazard(self.id_stage.instr):
                self.stall_cycles_data += 1
                self.stall_pipeline = True
            else:
                self.stall_pipeline = False
        else:
            self.stall_pipeline = False   # в последовательном режиме stall не нужен
    def execute(self):
        """
        Стадия EX (Execution).
        Продвигает инструкцию из ID в EX, если нет stall.
        Выполняет арифметические операции, MOV (частично), управляющие переходы.
        Для MUL/DIV устанавливает многотактность (remaining_cycles).
        """
        if self.stall_pipeline:
            return
        # Продвижение из ID в EX
        self.ex_stage = self.id_stage
        self.id_stage = PipelineStage()
        if self.ex_stage.instr is None:
            return
        instr = self.ex_stage.instr
        op = instr.opcode
        ops = instr.operands
        # Для MUL и DIV – 3 такта на выполнение (уровень C)
        if op in {"MUL", "DIV"}:
            self.ex_stage.remaining_cycles = 3
        else:
            self.ex_stage.remaining_cycles = 1
        if op == "HLT":
            self.halted = True
        elif op == "NOP":
            pass
        elif op == "JMP":
            if len(ops) != 1:
                raise RuntimeError("JMP requires 1 operand")
            label = ops[0]
            target = self.program.resolve_label(label)
            if target is None:
                raise RuntimeError(f"Undefined label {label}")
            self.ex_stage.pc_target = target
        elif op == "JZ":
            if len(ops) != 1:
                raise RuntimeError("JZ requires 1 operand")
            label = ops[0]
            target = self.program.resolve_label(label)
            if target is None:
                raise RuntimeError(f"Undefined label {label}")
            if self.state.z:
                self.ex_stage.pc_target = target
        elif op == "JNZ":
            if len(ops) != 1:
                raise RuntimeError("JNZ requires 1 operand")
            label = ops[0]
            target = self.program.resolve_label(label)
            if target is None:
                raise RuntimeError(f"Undefined label {label}")
            if not self.state.z:
                self.ex_stage.pc_target = target
        elif op == "CALL":
            if len(ops) != 1:
                raise RuntimeError("CALL requires 1 operand")
            label = ops[0]
            target = self.program.resolve_label(label)
            if target is None:
                raise RuntimeError(f"Undefined label {label}")
            self.ex_stage.result = self.state.pc   # сохраняем адрес возврата
            self.ex_stage.dest_type = "STACK"
            self.ex_stage.pc_target = target
        elif op == "RETI":
            self.ex_stage.dest_type = "STACK"
        elif op == "MOV":
            if len(ops) != 2:
                raise RuntimeError("MOV requires 2 operands")
            dest_type, dest_val = parse_operand(ops[0])
            src_type, src_val = parse_operand(ops[1])
            # Сохраняем типы и значения для стадий MEM и WB
            self.ex_stage.dest_type = dest_type
            self.ex_stage.dest_val = dest_val
            self.ex_stage.src_type = src_type
            self.ex_stage.src_val = src_val
            # Если источник – регистр или константа, результат известен сразу
            if src_type == 'REG':
                self.ex_stage.result = self.state.read_reg(src_val)
            elif src_type == 'IMM':
                self.ex_stage.result = src_val
            elif src_type in ('MEM', 'REG_IND'):
                # Чтение из памяти будет на стадии MEM
                self.ex_stage.result = None
            else:
                raise RuntimeError(f"MOV: unsupported source {src_type}")
        elif op in {"ADD", "SUB", "MUL", "DIV", "MOD"}:
            if len(ops) != 3:
                raise RuntimeError(f"{op} requires 3 operands")
            dest_type, dest_val = parse_operand(ops[0])
            src1_type, src1_val = parse_operand(ops[1])
            src2_type, src2_val = parse_operand(ops[2])
            if not (dest_type == 'REG' and src1_type == 'REG' and src2_type == 'REG'):
                raise RuntimeError(f"{op}: all operands must be registers")
            a = self.state.read_reg(src1_val)
            b = self.state.read_reg(src2_val)
            if op == "ADD":
                if MAX_NUM - a < b or (-MAX_NUM + 1 - a) > b:
                    raise RuntimeError("Overflow ADD")
                res = a + b
            elif op == "SUB":
                if a < (b - MAX_NUM + 1) or (MAX_NUM + b) < a:
                    raise RuntimeError("Overflow SUB")
                res = a - b
            elif op == "MUL":
                if b != 0 and ((MAX_NUM // b) < a or (a < ((-MAX_NUM + 1) // b))):
                    raise RuntimeError("Overflow MUL")
                res = a * b
            elif op == "DIV":
                if b == 0:
                    raise RuntimeError("Division by zero DIV")
                if a == -MAX_NUM + 1 and b == -1:
                    raise RuntimeError("Overflow DIV")
                res = a // b
            else:  # MOD
                if b == 0:
                    raise RuntimeError("Division by zero MOD")
                res = a % b
            self.ex_stage.result = res
            self.ex_stage.dest_type = 'REG'
            self.ex_stage.dest_val = dest_val
            # Устанавливаем флаг Z: 1, если результат <= 0 
            self.ex_stage.extra['z_flag'] = (res <= 0)
        elif op == "CMP":
            if len(ops) != 2:
                raise RuntimeError("CMP requires 2 operands")
            src1_type, src1_val = parse_operand(ops[0])
            src2_type, src2_val = parse_operand(ops[1])
            if not (src1_type == 'REG' and src2_type == 'REG'):
                raise RuntimeError("CMP: both operands must be registers")
            a = self.state.read_reg(src1_val)
            b = self.state.read_reg(src2_val)
            self.ex_stage.extra['z_flag'] = (a == b)   # стандартное сравнение на равенство
            self.ex_stage.dest_type = 'FLAG'
    def memory(self):
        """
        Стадия MEM (Memory Access).
        Продвигает инструкцию из EX в MEM, если EX завершила выполнение (remaining_cycles == 0).
        Для MOV выполняет загрузку из памяти (если источник – память) или запись в память
        (если приёмник – память). Для CALL/RETI выполняет стековые операции.
        """
        if self.ex_stage.instr is None:
            return
        if self.ex_stage.remaining_cycles > 0:
            return   # многотактная операция ещё не завершилась
        # Продвижение из EX в MEM
        self.mem_stage = self.ex_stage
        self.ex_stage = PipelineStage()
        if self.mem_stage.instr is None:
            return
        instr = self.mem_stage.instr
        op = instr.opcode
        if op == "MOV":
            dest_type = self.mem_stage.dest_type
            src_type = self.mem_stage.src_type
            dest_val = self.mem_stage.dest_val
            src_val = self.mem_stage.src_val
            # Чтение из памяти, если источник – память
            if src_type == 'MEM':
                addr = src_val
                self.mem_stage.result = self.state.read_mem(addr)
            elif src_type == 'REG_IND':
                addr = self.state.read_reg(src_val)
                self.mem_stage.result = self.state.read_mem(addr)
            # Запись в память, если приёмник – память
            if dest_type == 'MEM':
                addr = dest_val
                value = self.mem_stage.result
                if value is None:
                    raise RuntimeError("MOV: write to memory without value")
                self.state.write_mem(addr, value)
            elif dest_type == 'REG_IND':
                addr = self.state.read_reg(dest_val)
                value = self.mem_stage.result
                if value is None:
                    raise RuntimeError("MOV: write to memory without value")
                self.state.write_mem(addr, value)
        elif op in {"CALL", "RETI"}:
            if op == "CALL":
                ret_addr = self.mem_stage.result
                self.state.push(ret_addr)
            elif op == "RETI":
                ret_addr = self.state.pop()
                self.mem_stage.pc_target = ret_addr
                self.mem_stage.dest_type = 'PC'
    def writeback(self):
        """
        Стадия WB (Write Back).
        Продвигает инструкцию из MEM в WB.
        Фиксирует изменения в архитектурном состоянии: запись в регистр (MOV, арифметика),
        установка флага Z (CMP, арифметика), изменение PC для CALL/RETI.
        Увеличивает счётчик завершённых инструкций.
        """
        self.wb_stage = self.mem_stage
        self.mem_stage = PipelineStage()
        if self.wb_stage.instr is None:
            return
        instr = self.wb_stage.instr
        op = instr.opcode
        if op == "MOV":
            if self.wb_stage.dest_type == 'REG':
                value = self.wb_stage.result
                if value is None:
                    raise RuntimeError("MOV: result is None in WB")
                self.state.write_reg(self.wb_stage.dest_val, value)
        elif op in {"ADD", "SUB", "MUL", "DIV", "MOD"}:
            if self.wb_stage.dest_type == 'REG':
                self.state.write_reg(self.wb_stage.dest_val, self.wb_stage.result)
            if 'z_flag' in self.wb_stage.extra:
                self.state.set_z(1 if self.wb_stage.extra['z_flag'] else 0)
        elif op == "CMP":
            if 'z_flag' in self.wb_stage.extra:
                self.state.set_z(1 if self.wb_stage.extra['z_flag'] else 0)
        elif op in {"CALL", "RETI"}:
            if self.wb_stage.dest_type == 'PC':
                self.state.pc = self.wb_stage.pc_target
        self.instructions_committed += 1
    # --------------------------------------------------------
    # Основной цикл
    # --------------------------------------------------------
    def tick(self):
        """
        Один такт конвейера. Выполняет продвижение инструкций по стадиям
        в обратном порядке (от WB к IF), обрабатывает переходы и многотактные операции.
        """
        if self.debug and self.cycles > 0:
            self.debug_print()
        # Обработка перехода: если на EX был установлен pc_target, выполняем переход
        # и очищаем IF и ID (flush)
        if self.ex_stage.pc_target is not None:
            self.state.pc = self.ex_stage.pc_target
            self.flush(['IF', 'ID'])
            self.ex_stage.pc_target = None
        # Продвижение по стадиям (обратный порядок)
        self.writeback()
        self.memory()
        self.execute()
        self.decode()
        self.fetch()
        # Уменьшаем счётчик оставшихся тактов для многотактных операций
        if self.ex_stage.instr and self.ex_stage.remaining_cycles > 0:
            self.ex_stage.remaining_cycles -= 1
        # В последовательном режиме: как только инструкция покинула WB, снимаем блокировку IF
        if self.sequential and self.wb_stage.instr is not None:
            self.if_blocked = False
        self.cycles += 1
    def run(self):
        """Запуск конвейера до остановки (HLT)."""
        while not self.halted:
            self.tick()
            if self.cycles > MAX_CYCLES:
                raise RuntimeError("Too many cycles")
        self.drain()
    def drain(self):
        """
        Дренаж конвейера: продолжает тактирование, пока все стадии не освободятся.
        Это необходимо для завершения всех инструкций после HLT.
        """
        while (self.if_stage.instr is not None or
               self.id_stage.instr is not None or
               self.ex_stage.instr is not None or
               self.mem_stage.instr is not None or
               self.wb_stage.instr is not None):
            self.tick()
            if self.cycles > MAX_CYCLES:
                raise RuntimeError("Drain timeout")
        self.cycles -= 1
    def debug_print(self):
        """Вывод отладочной информации о состоянии конвейера и регистров."""
        print(f"Cycle {self.cycles}:")
        print(f"  IF:  {self.if_stage.instr if self.if_stage.instr else '-'}")
        print(f"  ID:  {self.id_stage.instr if self.id_stage.instr else '-'}   {'(STALL)' if self.stall_pipeline else ''}")
        print(f"  EX:  {self.ex_stage.instr if self.ex_stage.instr else '-'}   {f'(rem={self.ex_stage.remaining_cycles})' if self.ex_stage.instr else ''}")
        print(f"  MEM: {self.mem_stage.instr if self.mem_stage.instr else '-'}")
        print(f"  WB:  {self.wb_stage.instr if self.wb_stage.instr else '-'}")
        print(f"  State: PC={self.state.pc}, Z={self.state.z}, SP={self.state.sp}, REGS={self.state.regs}")
    def get_stats(self) -> dict:
        """
        Возвращает словарь со статистикой выполнения:
          - cycles                – общее количество тактов
          - instructions_committed – количество завершённых инструкций
          - CPI                   – среднее количество тактов на инструкцию
          - stall_data            – количество тактов простоя из-за RAW-зависимостей
          - stall_struct          – количество тактов простоя из-за структурных конфликтов (здесь не используется)
          - flush                 – количество очисток конвейера (из-за переходов)
        """
        return {
            "cycles": self.cycles,
            "instructions_committed": self.instructions_committed,
            "CPI": self.cycles / self.instructions_committed if self.instructions_committed else 0,
            "stall_data": self.stall_cycles_data,
            "stall_struct": self.stall_cycles_struct,
            "flush": self.flush_cycles,
        }
# ------------------------------------------------------------
# Точка входа
# ------------------------------------------------------------
def main(file: str = "program.txt", debug: bool = True, mode: str = "seq"):
    """
    Главная функция интерпретатора.
    Аргументы:
      file  – путь к файлу с программой
      debug – флаг отладочного вывода
      mode  – режим выполнения: "seq" – последовательный, "pipe" – конвейерный
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
    state = State()
    sequential = (mode == "seq")
    executor = PipelineExecutor(program, state, debug, sequential)
    try:
        executor.run()
    except Exception as e:
        print(f"Error during execution: {e}")
    print(f"Final state: {state}")
    stats = executor.get_stats()
    print(f"Stats: {stats}")
if __name__ == "__main__":
    main()
