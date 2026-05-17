export type Item = {
  id: string;
  title: string;
};

export function createItemStore() {
  let nextId = 3;
  const items: Item[] = [
    {id: '1', title: 'Seed accessibility IDs'},
    {id: '2', title: 'Record autonomous trace'},
  ];

  return {
    fetch(): Item[] {
      return [...items];
    },
    add(title: string): Item {
      const item = {id: String(nextId++), title};
      items.unshift(item);
      return item;
    },
  };
}
