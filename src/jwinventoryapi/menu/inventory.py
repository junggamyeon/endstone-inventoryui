from typing import overload, Callable
from endstone.inventory import ItemStack
from jwinventoryapi.util.item_utils import clone_item

class UIInventory:

    def __init__(self, size: int = 36, max_stack_size: int = 64,
                 slot_updated: Callable[[int], None] | None = None):
        self._size = size
        self._max_stack_size = max_stack_size
        self._slots: list[ItemStack | None] = [None] * size
        self._slot_updated = slot_updated
        self._batch_mode = False
        self._dirty_slots: set[int] = set()

    def begin_batch(self) -> None:
        self._batch_mode = True

    def end_batch(self) -> None:
        self._batch_mode = False
        if self._slot_updated is not None:
            for slot in self._dirty_slots:
                self._slot_updated(slot)
        self._dirty_slots.clear()

    def _notify(self, index: int) -> None:
        if self._batch_mode:
            self._dirty_slots.add(index)
            return
        if self._slot_updated is not None:
            self._slot_updated(index)

    @property
    def size(self) -> int:
        return self._size

    @property
    def max_stack_size(self) -> int:
        return self._max_stack_size

    def get_item(self, index: int) -> ItemStack:
        if not 0 <= index < self._size:
            raise IndexError(f"Slot index {index} out of range")
        item = self._slots[index]
        if item is None:
            return ItemStack("minecraft:air")
        return item

    def set_item(self, index: int, item: ItemStack | None) -> None:
        if not 0 <= index < self._size:
            raise IndexError(f"Slot index {index} out of range")
        self._slots[index] = item
        self._notify(index)

    def add_item(self, *args: ItemStack) -> dict[int, ItemStack]:
        leftover = {}
        for i, item in enumerate(args):
            if item is None or item.amount <= 0:
                continue
            remaining = clone_item(item)

            for slot_idx in range(self._size):
                if remaining.amount <= 0:
                    break
                slot_item = self._slots[slot_idx]
                if slot_item is not None and slot_item.is_similar(remaining):
                    cap = min(self._max_stack_size, slot_item.max_stack_size)
                    space = cap - slot_item.amount
                    if space > 0:
                        added = min(remaining.amount, space)
                        slot_item.amount += added
                        remaining.amount -= added
                        self._notify(slot_idx)

            for slot_idx in range(self._size):
                if remaining.amount <= 0:
                    break
                if self._slots[slot_idx] is None:
                    cap = min(self._max_stack_size, remaining.max_stack_size)
                    placed = min(remaining.amount, cap)
                    new_item = clone_item(remaining)
                    new_item.amount = placed
                    self._slots[slot_idx] = new_item
                    remaining.amount -= placed
                    self._notify(slot_idx)

            if remaining.amount > 0:
                leftover[i] = remaining
        return leftover

    def remove_item(self, *args: ItemStack) -> dict[int, ItemStack]:
        leftover = {}
        for i, item in enumerate(args):
            if item is None or item.amount <= 0:
                continue
            to_remove = item.amount
            for slot_idx in range(self._size):
                if to_remove <= 0:
                    break
                slot_item = self._slots[slot_idx]
                if slot_item is not None and slot_item.is_similar(item):
                    removed = min(to_remove, slot_item.amount)
                    slot_item.amount -= removed
                    to_remove -= removed
                    if slot_item.amount <= 0:
                        self._slots[slot_idx] = None
                    self._notify(slot_idx)
            if to_remove > 0:
                leftover_item = clone_item(item)
                leftover_item.amount = to_remove
                leftover[i] = leftover_item
        return leftover

    @property
    def contents(self) -> list[ItemStack | None]:
        return self._slots.copy()

    @contents.setter
    def contents(self, items: list[ItemStack | None]) -> None:
        for i in range(self._size):
            new_item = items[i] if i < len(items) else None
            old_item = self._slots[i]
            if old_item is not new_item:
                self._slots[i] = new_item
                self._notify(i)

    def contains(self, item, amount: int = None) -> bool:
        if isinstance(item, str):
            return any(s is not None and s.type.id == item for s in self._slots)
        elif isinstance(item, ItemStack):
            if amount is not None:
                count = sum(1 for s in self._slots if s is not None and s == item)
                return count >= amount
            return any(s is not None and s == item for s in self._slots)
        return False

    def contains_at_least(self, item, amount: int) -> bool:
        if isinstance(item, str):
            total = sum(s.amount for s in self._slots if s is not None and s.type.id == item)
            return total >= amount
        elif isinstance(item, ItemStack):
            total = sum(s.amount for s in self._slots if s is not None and s.is_similar(item))
            return total >= amount
        return False

    def all(self, item) -> dict[int, ItemStack]:
        result = {}
        if isinstance(item, str):
            for i, s in enumerate(self._slots):
                if s is not None and s.type.id == item:
                    result[i] = s
        elif isinstance(item, ItemStack):
            for i, s in enumerate(self._slots):
                if s is not None and s == item:
                    result[i] = s
        return result

    def first(self, item) -> int:
        if isinstance(item, str):
            for i, s in enumerate(self._slots):
                if s is not None and s.type.id == item:
                    return i
        elif isinstance(item, ItemStack):
            for i, s in enumerate(self._slots):
                if s is not None and s == item:
                    return i
        return -1

    @property
    def first_empty(self) -> int:
        for i, s in enumerate(self._slots):
            if s is None:
                return i
        return -1

    @property
    def is_empty(self) -> bool:
        return all(s is None for s in self._slots)

    def remove(self, item) -> None:
        if isinstance(item, str):
            for i, s in enumerate(self._slots):
                if s is not None and s.type.id == item:
                    self._slots[i] = None
                    self._notify(i)
        elif isinstance(item, ItemStack):
            for i, s in enumerate(self._slots):
                if s is not None and s == item:
                    self._slots[i] = None
                    self._notify(i)

    def clear(self, index: int = None) -> None:
        if index is not None:
            if 0 <= index < self._size:
                if self._slots[index] is not None:
                    self._slots[index] = None
                    self._notify(index)
        else:
            for i in range(self._size):
                if self._slots[i] is not None:
                    self._slots[i] = None
                    self._notify(i)

    def __len__(self) -> int:
        return self._size

    def __getitem__(self, index: int) -> ItemStack:
        return self.get_item(index)

    def __setitem__(self, index: int, item: ItemStack | None) -> None:
        self.set_item(index, item)

    def __contains__(self, item) -> bool:
        return self.contains(item)
