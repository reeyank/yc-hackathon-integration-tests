import React, {useMemo, useState} from 'react';
import {
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import {createItemStore, Item} from './src/itemStore';

type Screen = 'onboarding' | 'items' | 'create' | 'detail' | 'settings';

const DEMO_BROKEN_SAVE = true;

export default function App() {
  const store = useMemo(() => createItemStore(), []);
  const [screen, setScreen] = useState<Screen>('onboarding');
  const [items, setItems] = useState<Item[]>(store.fetch());
  const [selected, setSelected] = useState<Item | null>(null);
  const [toast, setToast] = useState('');

  function finishOnboarding() {
    setScreen('items');
  }

  function createItem(title: string) {
    const item = store.add(title);
    setItems(store.fetch());
    setSelected(item);
    setToast(DEMO_BROKEN_SAVE ? 'Save failed' : 'Saved');
    setScreen('detail');
  }

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.shell}>
        <Header screen={screen} onSettings={() => setScreen('settings')} />
        {screen === 'onboarding' ? (
          <OnboardingScreen onContinue={finishOnboarding} />
        ) : null}
        {screen === 'items' ? (
          <ItemListScreen
            items={items}
            onCreate={() => setScreen('create')}
            onSelect={item => {
              setSelected(item);
              setScreen('detail');
            }}
          />
        ) : null}
        {screen === 'create' ? (
          <CreateItemScreen onCancel={() => setScreen('items')} onSave={createItem} />
        ) : null}
        {screen === 'detail' && selected ? (
          <DetailScreen item={selected} toast={toast} onBack={() => setScreen('items')} />
        ) : null}
        {screen === 'settings' ? (
          <SettingsScreen onBack={() => setScreen('items')} />
        ) : null}
      </View>
    </SafeAreaView>
  );
}

function Header({screen, onSettings}: {screen: Screen; onSettings: () => void}) {
  return (
    <View style={styles.header}>
      <Text style={styles.brand} testID="app-title" accessibilityLabel="gbrain tasks">
        gbrain tasks
      </Text>
      {screen !== 'onboarding' ? (
        <Pressable
          testID="settings-btn"
          accessibilityLabel="Settings"
          style={styles.headerButton}
          onPress={onSettings}>
          <Text style={styles.headerButtonText}>Settings</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function OnboardingScreen({onContinue}: {onContinue: () => void}) {
  return (
    <View style={styles.screen} testID="onboarding-screen">
      <Text style={styles.title}>Own the testing loop</Text>
      <Text style={styles.copy}>A small app with enough structure for gbrain to discover flows.</Text>
      <Pressable
        testID="onboarding-continue-btn"
        accessibilityLabel="Continue"
        style={styles.primaryButton}
        onPress={onContinue}>
        <Text style={styles.primaryButtonText}>Continue</Text>
      </Pressable>
    </View>
  );
}

function ItemListScreen({
  items,
  onCreate,
  onSelect,
}: {
  items: Item[];
  onCreate: () => void;
  onSelect: (item: Item) => void;
}) {
  return (
    <View style={styles.screen} testID="item-list-screen">
      <View style={styles.rowBetween}>
        <Text style={styles.title}>Items</Text>
        <Pressable
          testID="add-item-btn"
          accessibilityLabel="Add item"
          style={styles.secondaryButton}
          onPress={onCreate}>
          <Text style={styles.secondaryButtonText}>Add</Text>
        </Pressable>
      </View>
      <ScrollView testID="item-list" accessibilityLabel="Item list">
        {items.map(item => (
          <Pressable
            key={item.id}
            testID={`item-row-${item.id}`}
            accessibilityLabel={`Open ${item.title}`}
            style={styles.listItem}
            onPress={() => onSelect(item)}>
            <Text style={styles.itemTitle}>{item.title}</Text>
            <Text style={styles.itemMeta}>tap for detail</Text>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

function CreateItemScreen({
  onCancel,
  onSave,
}: {
  onCancel: () => void;
  onSave: (title: string) => void;
}) {
  const [title, setTitle] = useState('');
  return (
    <View style={styles.screen} testID="create-item-screen">
      <Text style={styles.title}>Create item</Text>
      <TextInput
        testID="title-field"
        accessibilityLabel="Title"
        style={styles.input}
        value={title}
        placeholder="Title"
        onChangeText={setTitle}
      />
      <View style={styles.actions}>
        <Pressable
          testID="cancel-create-btn"
          accessibilityLabel="Cancel"
          style={styles.ghostButton}
          onPress={onCancel}>
          <Text style={styles.ghostButtonText}>Cancel</Text>
        </Pressable>
        <Pressable
          testID="save-item-btn"
          accessibilityLabel="Save"
          style={styles.primaryButton}
          onPress={() => onSave(title || 'Untitled item')}>
          <Text style={styles.primaryButtonText}>Save</Text>
        </Pressable>
      </View>
    </View>
  );
}

function DetailScreen({item, toast, onBack}: {item: Item; toast: string; onBack: () => void}) {
  return (
    <View style={styles.screen} testID="detail-screen">
      <Text style={styles.title}>{item.title}</Text>
      <Text style={styles.copy}>Detail view for the selected item.</Text>
      {toast ? (
        <Text
          testID="toast"
          accessibilityLabel={toast === 'Saved' ? 'Saved confirmation' : 'Save failed'}
          style={styles.toast}>
          {toast}
        </Text>
      ) : null}
      <Pressable
        testID="back-to-list-btn"
        accessibilityLabel="Back to list"
        style={styles.secondaryButton}
        onPress={onBack}>
        <Text style={styles.secondaryButtonText}>Back</Text>
      </Pressable>
    </View>
  );
}

function SettingsScreen({onBack}: {onBack: () => void}) {
  return (
    <View style={styles.screen} testID="settings-screen">
      <Text style={styles.title}>Settings</Text>
      <Text testID="settings-status" style={styles.copy}>
        Seeded data, local-only mode
      </Text>
      <Pressable
        testID="settings-back-btn"
        accessibilityLabel="Back to list"
        style={styles.secondaryButton}
        onPress={onBack}>
        <Text style={styles.secondaryButtonText}>Back</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: '#0A0E14'},
  shell: {flex: 1, padding: 24},
  header: {height: 56, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'},
  brand: {color: '#5EF6A4', fontSize: 20, fontWeight: '700'},
  headerButton: {paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6, backgroundColor: '#1C2530'},
  headerButtonText: {color: '#A8FFD0', fontWeight: '700'},
  screen: {flex: 1, gap: 18, justifyContent: 'center'},
  title: {color: '#F2FFF8', fontSize: 34, fontWeight: '800'},
  copy: {color: '#9BAAB8', fontSize: 16, lineHeight: 24},
  rowBetween: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'},
  listItem: {padding: 18, marginBottom: 12, borderRadius: 8, backgroundColor: '#121923'},
  itemTitle: {color: '#F2FFF8', fontSize: 18, fontWeight: '700'},
  itemMeta: {color: '#5A6B7A', marginTop: 4},
  input: {height: 52, borderRadius: 8, backgroundColor: '#121923', color: '#F2FFF8', paddingHorizontal: 16},
  actions: {flexDirection: 'row', gap: 12},
  primaryButton: {paddingHorizontal: 18, paddingVertical: 14, borderRadius: 8, backgroundColor: '#5EF6A4'},
  primaryButtonText: {color: '#06100B', fontSize: 16, fontWeight: '800'},
  secondaryButton: {paddingHorizontal: 16, paddingVertical: 12, borderRadius: 8, backgroundColor: '#1C2530'},
  secondaryButtonText: {color: '#A8FFD0', fontSize: 16, fontWeight: '800'},
  ghostButton: {paddingHorizontal: 16, paddingVertical: 12, borderRadius: 8, backgroundColor: '#121923'},
  ghostButtonText: {color: '#9BAAB8', fontSize: 16, fontWeight: '800'},
  toast: {color: '#5EF6A4', fontSize: 18, fontWeight: '800'},
});
