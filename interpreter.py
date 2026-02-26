import sys
import re
from typing import List, Dict, Tuple, Any

class SimpleAssembler:
    """Простой интерпретатор псевдо-ассемблера"""
    
    def __init__(self):
        # Состояние вычислительной системы
        self.pc = 0  # Счетчик команд
        self.memory = [0] * 256  # Память данных (256 ячеек)
        self.running = False  # Флаг выполнения программы
        
        # Внутреннее представление программы
        self.lines = []  # Исходные строки
        self.instructions = []  # Распарсенные инструкции
        self.labels = {}  # Метки: {имя_метки: адрес}
        
        # Таблица допустимых команд
        self.valid_instructions = {'HLT', 'NOP', 'JMP'}
    
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
        # Комментарии начинаются с '#'
        if '#' in line:
            line = line[:line.index('#')]
        return line.strip()
    
    def first_pass(self) -> bool:
        """Первый проход: сбор меток и проверка синтаксиса"""
        address = 0
        error_count = 0
        
        for i, raw_line in enumerate(self.lines, 1):
            # Удаляем комментарии и лишние пробелы
            line = self.remove_comments(raw_line)
            if not line:  # Пустая строка
                continue
            
            # Разделитель - пробел???
            parts = line.split()
            
            # Проверяем, является ли первый элемент меткой
            if parts[0].endswith(':'):
                label = parts[0][:-1]  # Убираем двоеточие
                
                if label in self.labels:
                    print(f"Ошибка (строка {i}): Метка '{label}' уже определена")
                    error_count += 1
                else:
                    self.labels[label] = address
                
                # Если после метки есть инструкция (только одна инструкция после метки???)
                if len(parts) > 1:
                    instr = parts[1]
                    if instr not in self.valid_instructions:
                        print(f"Ошибка (строка {i}): Неизвестная команда '{instr}'")
                        error_count += 1
                    address += 1
            else:
                # Обычная инструкция (тавталогия, но да бог с ней)
                instr = parts[0]
                if instr not in self.valid_instructions:
                    print(f"Ошибка (строка {i}): Неизвестная команда '{instr}'")
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
            
            # Пропускаем метки
            if parts[0].endswith(':'):
                if len(parts) > 1:
                    self.instructions.append((address, parts[1], parts[2:]))
                    address += 1
            else:
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
        max_executions = 1000  # Защита от зацикливания
        
        while self.running and executed_count < max_executions:
            if self.pc >= len(self.instructions):
                print(f"Ошибка: Счётчик команд {self.pc} превысил количество инструкций")
                break
            
            addr, instr, operands = self.instructions[self.pc]
            
            # Выполняем команду
            if instr == 'HLT':
                print("Программа завершена (HLT)")
                self.running = False
            elif instr == 'NOP':
                # Пустая операция
                pass
            elif instr == 'JMP':
                if len(operands) != 1:
                    print(f"Ошибка: JMP требует 1 операнд (метку)")
                    self.running = False
                    break
                
                label = operands[0]
                if label not in self.labels:
                    print(f"Ошибка: Метка '{label}' не найдена")
                    self.running = False
                    break
                
                # Безусловный переход
                self.pc = self.labels[label]
                print(f"  JMP -> {label} (адрес {self.pc})")
            else:
                # Эта ситуация не должна возникнуть после проверок
                print(f"Ошибка выполнения: неизвестная команда '{instr}'. Что-то пошло не по плану")
                self.running = False
            
            self.pc += 1
            executed_count += 1
        
        if executed_count >= max_executions:
            print("Ошибка: Превышен лимит выполнения (возможено зацикливание)")
            return False
        
        return True
    
    def run(self, filename: str) -> bool:
        """Полный цикл: загрузка, компиляция и выполнение"""
        print(f"Загрузка программы из файла: {filename}")
        
        # Шаг 1: Загрузка программы
        if not self.load_program(filename):
            return False
        
        print(f"Загружено строк: {len(self.lines)}")
        
        # Шаг 2: Первый проход (сбор меток и проверка команд)
        print("Первый проход: сбор меток и проверка синтаксиса...")
        if not self.first_pass():
            print("Ошибка компиляции: обнаружены синтаксические ошибки")
            return False
        
        print(f"Найдено меток: {len(self.labels)}")
        
        # Шаг 3: Второй проход (формирование внутреннего представления)
        print("Второй проход: формирование внутреннего представления...")
        if not self.second_pass():
            print("Ошибка при формировании внутреннего представления")
            return False
        
        print(f"Сформировано инструкций: {len(self.instructions)}")
        
        # Шаг 4: Выполнение программы
        print("\n--- Начало выполнения ---")
        result = self.execute()
        print("--- Конец выполнения ---")
        
        return result
    
    def print_state(self):
        """Отладочный вывод состояния"""
        print(f"\n--- Состояние ---")
        print(f"PC: {self.pc}")
        print(f"Память (первые 10 ячеек): {self.memory[:10]}")
        print(f"Метки: {self.labels}")


def main():
    """Главная функция"""
    if len(sys.argv) < 2:
        print("Использование: python interpreter.py <файл_программы>")
        print("Пример: python interpreter.py program.txt")
        return
    
    filename = sys.argv[1]
    
    # Создаем и запускаем интерпретатор
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