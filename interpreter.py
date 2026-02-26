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
        
        # Внутреннее представление программы
        self.lines = []  # Исходные строки
        self.instructions = []  # Распарсенные инструкции
        self.labels = {}  # Метки: {имя_метки: адрес}
        
        # Таблица допустимых команд
        self.valid_instructions = {'HLT', 'NOP', 'JMP', 'MOV'}
    
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
        - ('label', имя_метки) для меток
        """
        token = token.upper()
        
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
                return ('imm', value)  # Дополнительный код для положительных = само число
            else:
                raise ValueError(f"Число {value} выходит за пределы 16 бит (0-65535)")
        
        # Если не регистр и не число, считаем меткой
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
                if instr == 'JMP':
                    if len(parts) != 2:
                        print(f"Ошибка (строка {i}): JMP требует 1 операнд (метку)")
                        error_count += 1
                    else:
                        try:
                            op_type, op_val = self.parse_operand(parts[1])
                            if op_type != 'label':
                                # Если операнд распарсился как регистр или число - ошибка
                                print(f"Ошибка (строка {i}): JMP требует метку, получен {parts[1]}")
                                error_count += 1
                            # Для JMP не проверяем существование метки сейчас - это будет в execute
                        except ValueError as e:
                            print(f"Ошибка (строка {i}): {e}")
                            error_count += 1
                
                elif instr == 'MOV':
                    if len(parts) != 3:
                        print(f"Ошибка (строка {i}): MOV требует 2 операнда")
                        error_count += 1
                    else:
                        try:
                            # Проверяем первый операнд (должен быть регистром)
                            dest_type, dest_val = self.parse_operand(parts[1])
                            if dest_type != 'reg':
                                print(f"Ошибка (строка {i}): Первый операнд MOV должен быть регистром")
                                error_count += 1
                            
                            # Проверяем второй операнд
                            self.parse_operand(parts[2])
                            
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
    
    def execute(self) -> bool:
        """Выполнение программы"""
        if not self.instructions:
            print("Ошибка: Программа не загружена")
            return False
        
        self.pc = 0
        self.running = True
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
                
                elif instr == 'JMP':
                    if len(operands) != 1:
                        raise ValueError("JMP требует 1 операнд")
                    
                    op_type, label = self.parse_operand(operands[0])
                    if op_type != 'label':
                        raise ValueError(f"JMP требует метку, получен {operands[0]}")
                    
                    if label not in self.labels:
                        raise ValueError(f"Метка '{label}' не найдена")
                    
                    self.pc = self.labels[label]
                    print(f"  JMP -> {label} (адрес {self.pc})")
                    continue
                
                elif instr == 'MOV':
                    if len(operands) != 2:
                        raise ValueError("MOV требует 2 операнда")
                    
                    # Парсим операнды
                    dest_type, dest_val = self.parse_operand(operands[0])
                    src_type, src_val = self.parse_operand(operands[1])
                    
                    if dest_type != 'reg':
                        raise ValueError("Первый операнд MOV должен быть регистром")
                    
                    # Получаем значение источника
                    if src_type == 'reg':
                        value = self.registers[src_val]
                    elif src_type == 'imm':
                        value = src_val
                    else:  # label
                        raise ValueError("MOV не может использовать метку как источник")
                    
                    # Сохраняем в регистр назначения
                    self.registers[dest_val] = value
                    print(f"  MOV R{dest_val} <- {value} (0x{value:04X})")
                
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
        print("Регистры:")
        for i in range(0, 8, 4):
            reg_line = ""
            for j in range(4):
                if i + j < 8:
                    reg_line += f"R{i+j}: {self.registers[i+j]:5} (0x{self.registers[i+j]:04X})  "
            print(reg_line)
        print(f"Память (первые 10 ячеек): {[f'{x:04X}' for x in self.memory[:10]]}")
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