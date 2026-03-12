import sys
from typing import List, Dict, Tuple, Any, Union

class SimpleAssembler:
    """Простой интерпретатор псевдо-ассемблера"""

    def __init__(self):
        # Состояние вычислительной системы
        self.pc = 0  # Счетчик команд
        self.registers = [0] * 8  # 8 регистров R0-R7
        self.memory = [0] * 256  # Память данных (256 ячеек)
        self.running = False  # Флаг выполнения программы
        self.z_flag = False  # Флаг нуля (Z)

        # Внутреннее представление программы
        self.lines = []  # Исходные строки
        self.instructions = []  # Распарсенные инструкции
        self.labels = {}  # Метки: {имя_метки: адрес}

        # Таблица допустимых команд
        self.valid_instructions = {
            'HLT', 'NOP', 'JMP', 'JZ', 'JNZ',  # Управление
            'MOV', 'CMP',                       # Пересылки
            'ADD', 'SUB', 'MUL', 'DIV', 'MOD'    # Арифметика
        }

    def load_program(self, filename: str) -> bool:
        """Загрузка программы из файла"""
        try:
            with open(filename, 'r', encoding='utf-8') as file:
                self.lines = [line.upper() for line in file.readlines()]
            return True
        except FileNotFoundError:
            print(f"Ошибка: Файл '{filename}' не найден")
            return False
        except Exception as e:
            print(f"Ошибка при чтении файла: {e}")
            return False

    def remove_comments(self, line: str) -> str:
        """Удаление комментариев из строки"""
        if '#' in line:
            line = line[:line.index('#')]
        return line.strip()

    def parse_operand(self, token: str) -> Tuple[str, Union[int, str]]:
        """
        Парсинг операнда.
        Возвращает кортеж (тип, значение):
        - ('reg', номер_регистра) для R0-R7
        - ('imm', число) для констант (только положительные десятичные)
        - ('mem', адрес) для [адрес]
        - ('label', имя_метки) для меток
        """
        token = token.upper()

        # Проверка на память [адрес]
        if token.startswith('[') and token.endswith(']'):
            addr_token = token[1:-1]  # убираем скобки
            if addr_token.isdigit():
                addr = int(addr_token)
                if 0 <= addr <= 255:
                    return ('mem', addr)
                else:
                    raise ValueError(f"Адрес памяти {addr} вне диапазона (0-255)")
            else:
                raise ValueError(f"Неверный адрес памяти: {addr_token}")

        # Проверка на регистр (только R0-R7)
        if token.startswith('R') and len(token) == 2:  # Только R0..R7
            if token[1].isdigit():
                reg_num = int(token[1])
                if 0 <= reg_num <= 7:
                    return ('reg', reg_num)
                # R8, R9 - метки (продолжаем проверку)

        # Проверка на число (только положительные десятичные)
        if token.isdigit():  # Только цифры, без минуса
            value = int(token)

            # Проверка на 16-битное беззнаковое число
            if 0 <= value <= 65535:
                return ('imm', value)
            else:
                raise ValueError(f"Число {value} выходит за пределы 16 бит (0-65535)")

        # Если не регистр, не число и не память, считаем меткой
        if token and token[0].isalpha():
            return ('label', token)
        else:
            raise ValueError(f"Неверный операнд: {token}")

    def first_pass(self) -> bool:
        """Первый проход: сбор меток и проверка синтаксиса"""
        address = 0
        error_count = 0

        for i, raw_line in enumerate(self.lines, 1):
            line = self.remove_comments(raw_line)
            if not line:
                continue

            parts = line.split()

            # Проверка на метку
            if parts[0].endswith(':'):
                label = parts[0][:-1]

                if label in self.labels:
                    print(f"Ошибка (строка {i}): Метка '{label}' уже определена")
                    error_count += 1
                else:
                    self.labels[label] = address

                # Игнорируем всё после метки
                continue
            else:
                instr = parts[0]
                if instr not in self.valid_instructions:
                    print(f"Ошибка (строка {i}): Неизвестная команда '{instr}'")
                    error_count += 1

                # Проверка синтаксиса команд
                if instr in ['JMP', 'JZ', 'JNZ']:
                    if len(parts) != 2:
                        print(f"Ошибка (строка {i}): {instr} требует 1 операнд (метку)")
                        error_count += 1
                    else:
                        try:
                            op_type, op_val = self.parse_operand(parts[1])
                            if op_type != 'label':
                                print(f"Ошибка (строка {i}): {instr} требует метку, получен {parts[1]}")
                                error_count += 1
                        except ValueError as e:
                            print(f"Ошибка (строка {i}): {e}")
                            error_count += 1

                elif instr == 'MOV':
                    if len(parts) != 3:
                        print(f"Ошибка (строка {i}): MOV требует 2 операнда")
                        error_count += 1
                    else:
                        try:
                            # Проверяем оба операнда
                            dest_type, dest_val = self.parse_operand(parts[1])
                            src_type, src_val = self.parse_operand(parts[2])

                            # Проверка допустимых комбинаций:
                            # 1. регистр <- регистр/число
                            # 2. память <- регистр
                            # 3. регистр <- память

                            if dest_type == 'reg':
                                if src_type not in ['reg', 'imm', 'mem']:
                                    print(f"Ошибка (строка {i}): Недопустимый источник для регистра")
                                    error_count += 1
                            elif dest_type == 'mem':
                                if src_type != 'reg':
                                    print(f"Ошибка (строка {i}): В память можно сохранять только из регистра")
                                    error_count += 1
                            else:
                                print(f"Ошибка (строка {i}): Недопустимый приемник MOV")
                                error_count += 1

                        except ValueError as e:
                            print(f"Ошибка (строка {i}): {e}")
                            error_count += 1

                elif instr == 'CMP':
                    if len(parts) != 3:
                        print(f"Ошибка (строка {i}): CMP требует 2 операнда (регистры)")
                        error_count += 1
                    else:
                        try:
                            op1_type, op1_val = self.parse_operand(parts[1])
                            op2_type, op2_val = self.parse_operand(parts[2])

                            if op1_type != 'reg' or op2_type != 'reg':
                                print(f"Ошибка (строка {i}): CMP требует два операнда регистра, получено {parts[1]}, {parts[2]}")
                                error_count += 1
                        except ValueError as e:
                            print(f"Ошибка (строка {i}): {e}")
                            error_count += 1

                elif instr in ['ADD', 'SUB', 'MUL', 'DIV', 'MOD']:
                    # 3-адресная модель: ADD Rdest Rsrc1 Rsrc2
                    if len(parts) != 4:
                        print(f"Ошибка (строка {i}): {instr} требует 3 операнда: Rdest Rsrc1 Rsrc2")
                        error_count += 1
                    else:
                        try:
                            # Проверяем операнды
                            dest_type, dest_val = self.parse_operand(parts[1])
                            src1_type, src1_val = self.parse_operand(parts[2])
                            src2_type, src2_val = self.parse_operand(parts[3])

                            # Первый операнд должен быть регистром
                            if dest_type != 'reg':
                                print(f"Ошибка (строка {i}): Первый операнд должен быть регистром")
                                error_count += 1

                            # Второй операнд может быть регистром
                            if src1_type != 'reg':
                                print(f"Ошибка (строка {i}): Второй операнд должен быть регистром")
                                error_count += 1

                            # Третий операнд может быть регистром
                            if src2_type != 'reg':
                                print(f"Ошибка (строка {i}): Третий операнд должен быть регистром")
                                error_count += 1

                            # Для DIV и MOD проверка деления на ноль будет в execute

                        except ValueError as e:
                            print(f"Ошибка (строка {i}): {e}")
                            error_count += 1

                address += 1

        return error_count == 0

    def second_pass(self) -> bool:
        """Второй проход: формирование внутреннего представления"""
        address = 0
        error_count = 0

        for i, raw_line in enumerate(self.lines, 1):
            line = self.remove_comments(raw_line)
            if not line:
                continue

            parts = line.split()

            # Пропускаем строки с метками
            if parts[0].endswith(':'):
                continue
            else:
                # Сохраняем инструкцию с операндами как есть
                self.instructions.append((address, parts[0], parts[1:]))
                address += 1

        return error_count == 0

    def get_operand_value(self, op_type: str, op_val: Union[int, str]) -> int:
        """Получение значения операнда"""
        if op_type == 'reg':
            return self.registers[op_val]
        elif op_type == 'imm':
            return op_val
        elif op_type == 'mem':
            return self.memory[op_val]
        else:
            raise ValueError(f"Невозможно получить значение для типа {op_type}")

    def execute(self) -> bool:
        """Выполнение программы"""
        if not self.instructions:
            print("Ошибка: Программа не загружена")
            return False

        self.pc = 0
        self.running = True
        self.z_flag = False
        executed_count = 0
        max_executions = 1000

        while self.running and executed_count < max_executions:
            if self.pc >= len(self.instructions):
                print(f"Ошибка: Счётчик команд {self.pc} превысил количество инструкций")
                break

            addr, instr, operands = self.instructions[self.pc]

            try:
                if instr == 'HLT':
                    print("Программа завершена (HLT)")
                    self.running = False

                elif instr == 'NOP':
                    pass

                elif instr in ['JMP', 'JZ', 'JNZ']:
                    if len(operands) != 1:
                        raise ValueError(f"{instr} требует 1 операнд")

                    op_type, label = self.parse_operand(operands[0])
                    if op_type != 'label':
                        raise ValueError(f"{instr} требует метку, получен {operands[0]}")

                    if label not in self.labels:
                        raise ValueError(f"Метка '{label}' не найдена")

                    should_jump = False
                    if instr == 'JMP':
                        should_jump = True
                    elif instr == 'JZ':
                        should_jump = self.z_flag
                    elif instr == 'JNZ':
                        should_jump = not self.z_flag

                    if should_jump:
                        self.pc = self.labels[label]
                        print(f"  {instr} -> {label} (адрес {self.pc})")
                        continue
                    else:
                        print(f"  {instr} -> {label} (условие не выполнено)")

                elif instr == 'MOV':
                    if len(operands) != 2:
                        raise ValueError("MOV требует 2 операнда")

                    # Парсим операнды
                    dest_type, dest_val = self.parse_operand(operands[0])
                    src_type, src_val = self.parse_operand(operands[1])

                    # Выполняем MOV в зависимости от типов
                    if dest_type == 'reg' and src_type == 'reg':
                        # регистр <- регистр
                        self.registers[dest_val] = self.registers[src_val]
                        print(f"  MOV R{dest_val} <- R{src_val} ({self.registers[dest_val]}) ")

                    elif dest_type == 'reg' and src_type == 'imm':
                        # регистр <- число
                        self.registers[dest_val] = src_val
                        print(f"  MOV R{dest_val} <- {src_val}")

                    elif dest_type == 'reg' and src_type == 'mem':
                        # регистр <- память
                        self.registers[dest_val] = self.memory[src_val]
                        print(f"  MOV R{dest_val} <- [{src_val}] ({self.memory[src_val]}) ")

                    elif dest_type == 'mem' and src_type == 'reg':
                        # память <- регистр
                        self.memory[dest_val] = self.registers[src_val]
                        print(f"  MOV [{dest_val}] <- R{src_val} ({self.registers[src_val]}) ")

                    else:
                        raise ValueError(f"Недопустимая комбинация операндов MOV: {dest_type} <- {src_type}")

                elif instr == 'CMP':
                    if len(operands) != 2:
                        raise ValueError("CMP требует 2 операнда")

                    op1_type, op1_val = self.parse_operand(operands[0])
                    op2_type, op2_val = self.parse_operand(operands[1])

                    if op1_type != 'reg' or op2_type != 'reg':
                        raise ValueError(f"CMP требует два операнда регистра, получено {operands[0]}, {operands[1]}")

                    val1 = self.registers[op1_val]
                    val2 = self.registers[op2_val]

                    self.z_flag = (val1 == val2)
                    print(f"  CMP R{op1_val} ({val1}), R{op2_val} ({val2}) -> Z={self.z_flag}")

                elif instr in ['ADD', 'SUB', 'MUL', 'DIV', 'MOD']:
                    if len(operands) != 3:
                        raise ValueError(f"{instr} требует 3 операнда")

                    # Парсим операнды
                    dest_type, dest_val = self.parse_operand(operands[0])
                    src1_type, src1_val = self.parse_operand(operands[1])
                    src2_type, src2_val = self.parse_operand(operands[2])

                    # Проверяем типы
                    if dest_type != 'reg':
                        raise ValueError("Первый операнд должен быть регистром")

                    if src1_type != 'reg':
                        raise ValueError("Второй операнд должен быть регистром")

                    if src2_type != 'reg':
                        raise ValueError("Третий операнд должен быть регистром")

                    # Получаем значения
                    val1 = self.get_operand_value(src1_type, src1_val)
                    val2 = self.get_operand_value(src2_type, src2_val)

                    # Выполняем операцию
                    result = 0
                    full_result = 0  # Для отладочного вывода
                    max_num = 0xFFFF

                    if instr == 'ADD':
                        # Проверка на переполнение
                        if max_num - val1 < val2 or (-max_num+1-val1) > val2:
                            self.running = False
                            full_result = max_num
                            print(f"  ПопыткаADD R{dest_val} <- {val1} + {val2} = {full_result} (OVERFLOW, stored {full_result & 0xFFFF})")
                            print("Программа завершена (HLT из-за переполнения)")
                        else:
                            full_result = val1 + val2
                            print(f"  ADD R{dest_val} <- {val1} + {val2} = {full_result}")
                            result = full_result

                    elif instr == 'SUB':
                        # Проверка на переполнение
                        if val1 < (val2-max_num+1) or (max_num+val2) < val1:
                            self.running = False
                            full_result = max_num
                            print(f"  Попытка SUB R{dest_val} <- {val1} - {val2} = {full_result} (OVERFLOW, stored {full_result & 0xFFFF})")
                            print("Программа завершена (HLT из-за переполнения)")
                        else:
                            full_result = val1 - val2
                            print(f"  SUB R{dest_val} <- {val1} - {val2} = {full_result}")
                            result = full_result

                    elif instr == 'MUL':
                        # Проверка на переполнение
                        if val2 != 0 and ((max_num // val2) < val1 or (val1 < ((-max_num+1) // val2))):
                            self.running = False
                            full_result = max_num
                            print(f"  Попытка MUL R{dest_val} <- {val1} * {val2} = {full_result} (OVERFLOW, stored {full_result & 0xFFFF})")
                            print("Программа завершена (HLT из-за переполнения)")
                        else:
                            full_result = val1 * val2
                            print(f"  MUL R{dest_val} <- {val1} * {val2} = {full_result}")
                            result = full_result   

                    elif instr == 'DIV':
                        if val2 == 0:
                            raise ValueError("Деление на ноль")
                        # Переполнение для дополнительного кода: минимальное число / -1
                        if val1 == -max_num+1 and val2 == -1:
                            self.running = False
                            full_result = -max_num
                            print(f"  Попытка DIV R{dest_val} <- {val1} / {val2} = {full_result} (OVERFLOW, stored {full_result & 0xFFFF})")
                            print("Программа завершена (HLT из-за переполнения)")
                        else:
                            result = val1 // val2
                            print(f"  DIV R{dest_val} <- {val1} / {val2} = {result}")

                    elif instr == 'MOD':
                        if val2 == 0:
                            raise ValueError("Деление на ноль (MOD)")
                        result = (val1 % val2)
                        print(f"  MOD R{dest_val} <- {val1} % {val2} = {result}")

                    # Сохраняем результат
                    self.registers[dest_val] = result
                    if full_result < 0:
                        self.z_flag = True

                else:
                    raise ValueError(f"Неизвестная команда '{instr}'")

            except (ValueError, IndexError) as e:
                print(f"Ошибка выполнения (адрес {addr}): {e}")
                self.running = False
                break

            self.pc += 1
            executed_count += 1

        if executed_count >= max_executions:
            print("Ошибка: Превышен лимит выполнения (возможно зацикливание)")
            return False

        return True

    def run(self, filename: str) -> bool:
        """Полный цикл: загрузка, компиляция и выполнение"""
        print(f"Загрузка программы из файла: {filename}")

        if not self.load_program(filename):
            return False

        print(f"Загружено строк: {len(self.lines)}")

        print("Первый проход: сбор меток и проверка синтаксиса...")
        if not self.first_pass():
            print("Ошибка компиляции: обнаружены синтаксические ошибки")
            return False

        print(f"Найдено меток: {len(self.labels)}")

        print("Второй проход: формирование внутреннего представления...")
        if not self.second_pass():
            print("Ошибка при формировании внутреннего представления")
            return False

        print(f"Сформировано инструкций: {len(self.instructions)}")

        print("\n--- Начало выполнения ---")
        result = self.execute()
        print("--- Конец выполнения ---")

        return result

    def print_state(self):
        """Отладочный вывод состояния"""
        print(f"\n--- Состояние ---")
        print(f"PC: {self.pc}")
        print(f"Z: {self.z_flag}")
        print("Регистры:")
        for i in range(0, 8, 4):
            reg_line = ""
            for j in range(4):
                if i + j < 8:
                    reg_line += f"R{i+j}: {self.registers[i+j]:5} (0x{self.registers[i+j]:04X})  "
            print(reg_line)
        print(f"Память (первые 10 ячеек): {[self.memory[i] for i in range(10)]}")
        print(f"Метки: {self.labels}")

def main():
    """Главная функция"""
    if len(sys.argv) < 2:
        print("Использование: python interpreter.py <файл_программы>")
        print("Пример: python interpreter.py program.txt")
        return

    filename = sys.argv[1]

    asm = SimpleAssembler()
    success = asm.run(filename)

    if success:
        print("\nПрограмма выполнена успешно!")
        asm.print_state()
    else:
        print("\nОшибка выполнения программы")
        sys.exit(1)


if __name__ == "__main__":
    main()