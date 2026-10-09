import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Keyboard,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StatusBar as RNStatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

const API_URL = 'https://at-product-scout.onrender.com/api/scout';

// Pipeline na serveru dělá tři sub-agenty, supervizora a případnou opravu.
const REQUEST_TIMEOUT_MS = 240000;

const C = {
  background: '#0f172a',
  panel: '#1e293b',
  border: '#334155',
  text: '#f1f5f9',
  muted: '#94a3b8',
  green: '#22c55e',
  red: '#f87171',
  amber: '#fbbf24',
};

const BUDGET_PRESETS = [
  { label: '100 €', value: 100 },
  { label: '250 €', value: 250 },
  { label: '500 €', value: 500 },
  { label: 'Bez limitu', value: null },
];

const PRIORITIES = [
  { label: 'Max Úspora', value: 'cheapest_possible' },
  { label: 'Vyváženo', value: 'balanced' },
  { label: 'Značkové', value: 'premium_brands' },
];

const BADGE_THEMES = {
  'NEJLEVNĚJŠÍ FUNKČNÍ VOLBA': {
    accent: '#38bdf8',
    surface: '#102033',
    chip: '#14304d',
    tagline: 'NEJNIŽŠÍ CENA',
  },
  'NEJLEPŠÍ CENA / VÝKON': {
    accent: '#22c55e',
    surface: '#0f2318',
    chip: '#14361f',
    tagline: 'DOPORUČENO',
  },
  'MODERNÍ TREND / INOVACE': {
    accent: '#a78bfa',
    surface: '#1b1733',
    chip: '#2a2150',
    tagline: 'TREND',
  },
};

const FALLBACK_THEME = {
  accent: '#94a3b8',
  surface: '#1e293b',
  chip: '#334155',
  tagline: 'VÝBĚR',
};

const LIQUIDITY_LEVELS = {
  'Vysoká (prodá se do týdne)': { filled: 3, color: C.green, short: 'Vysoká – prodá se do týdne' },
  'Střední poptávka': { filled: 2, color: C.amber, short: 'Střední poptávka' },
  'Nízká (leží měsíce)': { filled: 1, color: C.red, short: 'Nízká – leží měsíce' },
};

const PIPELINE_STAGES = [
  'Agent prohledává otevřený internet…',
  'Srovnává rakouské e-shopy, EU sklady a výrobce…',
  'Filtruje šunt bez certifikací a čte testy…',
  'Bazarový analytik počítá hodnotu na Willhabenu…',
  'Supervizor ověřuje cenu, URL a zemi odeslání…',
];

function formatEur(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return 'cena na dotaz';
  }
  return `${amount.toFixed(2).replace('.', ',')} €`;
}

function parseBudget(text) {
  const normalized = text.replace(',', '.').replace(/[^0-9.]/g, '');
  if (!normalized) {
    return null;
  }
  const amount = Number.parseFloat(normalized);
  return Number.isFinite(amount) && amount > 0 ? amount : null;
}

function messageFromErrorPayload(payload, status) {
  const detail = payload?.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const first = detail.find((entry) => typeof entry?.msg === 'string');
    if (first) {
      return `Dotaz se nepodařilo zpracovat: ${first.msg}`;
    }
  }
  if (status === 429) {
    return 'Překročen limit analytické služby. Zkus to prosím za chvíli.';
  }
  if (status >= 500) {
    return 'Server analytika hlásí chybu. Zkus to prosím znovu.';
  }
  return `Server odpověděl chybou ${status}.`;
}

async function fetchReport(body, signal) {
  const response = await fetch(API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    throw new Error(messageFromErrorPayload(payload, response.status));
  }
  if (!Array.isArray(payload?.items) || payload.items.length === 0) {
    throw new Error('Supervizor nevrátil žádné karty. Zkus dotaz formulovat jinak.');
  }
  return payload;
}

function ChoiceRow({ options, isActive, onSelect }) {
  return (
    <View style={styles.choiceRow}>
      {options.map((option) => {
        const active = isActive(option);
        return (
          <Pressable
            key={option.label}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            onPress={() => onSelect(option)}
            style={({ pressed }) => [
              styles.choiceChip,
              active && styles.choiceChipActive,
              pressed && styles.choiceChipPressed,
            ]}
          >
            <Text style={[styles.choiceText, active && styles.choiceTextActive]}>
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function LiquidityMeter({ liquidity }) {
  const level = LIQUIDITY_LEVELS[liquidity] ?? { filled: 0, color: C.muted, short: liquidity };
  return (
    <View style={styles.liquidityRow}>
      <View style={styles.meterTrack}>
        {[0, 1, 2].map((index) => (
          <View
            key={index}
            style={[
              styles.meterSegment,
              { backgroundColor: index < level.filled ? level.color : '#1f2937' },
            ]}
          />
        ))}
      </View>
      <Text style={[styles.liquidityText, { color: level.color }]}>{level.short}</Text>
    </View>
  );
}

function buyUrlFor(item) {
  if (item?.buy_url) {
    return item.buy_url;
  }
  const name = (item?.original_title || item?.name_cz || '').trim();
  if (!name) {
    return '';
  }
  return `https://www.google.at/search?tbm=shop&q=${encodeURIComponent(name)}`;
}

function Bullet({ symbol, color, children }) {
  return (
    <View style={styles.bulletRow}>
      <Text style={[styles.bulletSymbol, { color }]}>{symbol}</Text>
      <Text style={styles.bulletText}>{children}</Text>
    </View>
  );
}

function ProductCard({ item, onOpenOffers }) {
  const theme = BADGE_THEMES[item.badge] ?? FALLBACK_THEME;
  const buyUrl = buyUrlFor(item);

  return (
    <View style={[styles.card, { borderColor: theme.accent, backgroundColor: theme.surface }]}>
      <View style={styles.cardHeader}>
        <View style={[styles.cardChip, { backgroundColor: theme.chip, borderColor: theme.accent }]}>
          <Text style={[styles.cardChipText, { color: theme.accent }]}>{theme.tagline}</Text>
        </View>
        <Text style={[styles.cardBadge, { color: theme.accent }]}>{item.badge}</Text>
      </View>

      <Text style={styles.cardTitle}>{item.name_cz}</Text>
      <Text style={styles.cardOriginal}>{item.original_title}</Text>

      <View style={styles.originRow}>
        <View style={[styles.originChip, { borderColor: theme.accent, backgroundColor: theme.chip }]}>
          <Text style={[styles.originChipText, { color: theme.accent }]}>
            {item.offer_origin || 'Původ nabídky'}
          </Text>
        </View>
        {item.ship_from_country ? (
          <Text style={styles.shipText}>Odeslání: {item.ship_from_country}</Text>
        ) : null}
      </View>

      <View style={styles.priceRow}>
        <View>
          <Text style={styles.priceCaption}>Nalezená nabídka</Text>
          <Text style={[styles.price, { color: theme.accent }]}>
            {formatEur(item.estimated_price_eur)}
          </Text>
        </View>
        <View style={styles.usedChip}>
          <Text style={styles.usedChipLabel}>Willhaben odhad</Text>
          <Text style={styles.usedChipValue}>{formatEur(item.willhaben_used_price_eur)}</Text>
        </View>
      </View>

      <Text style={styles.sectionLabel}>Výhody</Text>
      {item.pros?.map((pro, index) => (
        <Bullet key={`pro-${index}`} symbol="+" color={C.green}>
          {pro}
        </Bullet>
      ))}

      <Text style={styles.sectionLabel}>Kompromisy</Text>
      {item.cons?.map((con, index) => (
        <Bullet key={`con-${index}`} symbol="−" color={C.red}>
          {con}
        </Bullet>
      ))}

      <Text style={styles.sectionLabel}>Likvidita na Willhabenu</Text>
      <LiquidityMeter liquidity={item.willhaben_liquidity} />

      <Text style={styles.sectionLabel}>Pro koho</Text>
      <Text style={styles.targetText}>{item.verdict_target}</Text>

      <View style={styles.linkRow}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Koupit nebo zobrazit nabídky na Google Shopping"
          disabled={!buyUrl}
          onPress={() => onOpenOffers(buyUrl)}
          style={({ pressed }) => [
            styles.offerButton,
            styles.offerButtonPrimary,
            { backgroundColor: pressed ? theme.chip : theme.accent },
            !buyUrl && styles.offerButtonDisabled,
          ]}
        >
          <Text style={styles.offerButtonPrimaryText}>Koupit / Nabídky</Text>
        </Pressable>
        {item.geizhals_url ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Otevřít srovnání na Geizhals"
            onPress={() => onOpenOffers(item.geizhals_url)}
            style={({ pressed }) => [
              styles.offerButton,
              { borderColor: theme.accent, backgroundColor: pressed ? theme.chip : 'transparent' },
            ]}
          >
            <Text style={[styles.offerButtonText, { color: theme.accent }]}>Geizhals</Text>
          </Pressable>
        ) : null}
        {item.idealo_url ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Otevřít srovnání na Idealo"
            onPress={() => onOpenOffers(item.idealo_url)}
            style={({ pressed }) => [
              styles.offerButton,
              { borderColor: theme.accent, backgroundColor: pressed ? theme.chip : 'transparent' },
            ]}
          >
            <Text style={[styles.offerButtonText, { color: theme.accent }]}>Idealo</Text>
          </Pressable>
        ) : null}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Zkontrolovat bazar na Willhabenu"
          disabled={!item.willhaben_url}
          onPress={() => onOpenOffers(item.willhaben_url)}
          style={({ pressed }) => [
            styles.offerButton,
            { borderColor: theme.accent, backgroundColor: pressed ? theme.chip : 'transparent' },
            !item.willhaben_url && styles.offerButtonDisabled,
          ]}
        >
          <Text style={[styles.offerButtonText, { color: theme.accent }]}>Bazar Willhaben</Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function App() {
  const [queryText, setQueryText] = useState('');
  const [budgetText, setBudgetText] = useState('250');
  const [priority, setPriority] = useState('balanced');
  const [report, setReport] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [stageIndex, setStageIndex] = useState(0);
  const [errorMessage, setErrorMessage] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);
  const abortRef = useRef(null);

  useEffect(() => {
    if (!isLoading) {
      setStageIndex(0);
      return undefined;
    }
    const timer = setInterval(() => {
      setStageIndex((current) => Math.min(current + 1, PIPELINE_STAGES.length - 1));
    }, 7000);
    return () => clearInterval(timer);
  }, [isLoading]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const budget = parseBudget(budgetText);

  const handleSearch = useCallback(async () => {
    const trimmed = queryText.trim();
    if (!trimmed) {
      setErrorMessage('Nejdřív napiš, co chceš najít.');
      return;
    }

    Keyboard.dismiss();
    abortRef.current?.abort();

    const controller = new AbortController();
    abortRef.current = controller;
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    setIsLoading(true);
    setErrorMessage(null);
    setReport(null);
    setHasSearched(true);

    try {
      const result = await fetchReport(
        { query: trimmed, max_budget: parseBudget(budgetText), priority },
        controller.signal,
      );
      setReport(result);
    } catch (error) {
      if (error?.name === 'AbortError') {
        setErrorMessage('Analýza trhu trvala příliš dlouho a byla přerušena. Zkus to znovu.');
      } else if (error instanceof TypeError) {
        setErrorMessage(
          `Nepodařilo se spojit se serverem (${API_URL}). ` +
            'Zkontroluj připojení k internetu a že backend na Renderu běží.',
        );
      } else {
        setErrorMessage(error?.message ?? 'Nastala neznámá chyba při analýze trhu.');
      }
    } finally {
      clearTimeout(timeoutId);
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
      setIsLoading(false);
    }
  }, [budgetText, priority, queryText]);

  const handleOpenOffers = useCallback(async (url) => {
    if (!url) {
      return;
    }
    try {
      await Linking.openURL(url);
    } catch {
      setErrorMessage('Odkaz se nepodařilo otevřít v prohlížeči telefonu.');
    }
  }, []);

  const canSubmit = queryText.trim().length > 0 && !isLoading;

  return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" backgroundColor={C.background} />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.header}>
          <Text style={styles.headerTitle}>AT Product Scout</Text>
          <Text style={styles.headerSubtitle}>
            Otevřený internet, doručení do Rakouska
          </Text>
        </View>

        <ScrollView
          style={styles.flex}
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.panel}>
            <Text style={styles.panelLabel}>Produkt</Text>
            <TextInput
              style={styles.input}
              value={queryText}
              onChangeText={setQueryText}
              placeholder="Např. espresso kávovar do kanceláře"
              placeholderTextColor="#64748b"
              selectionColor={C.green}
              returnKeyType="search"
              editable={!isLoading}
              onSubmitEditing={handleSearch}
            />

            <Text style={styles.panelLabel}>Cenový strop (€)</Text>
            <TextInput
              style={styles.input}
              value={budgetText}
              onChangeText={setBudgetText}
              placeholder="Bez limitu"
              placeholderTextColor="#64748b"
              selectionColor={C.green}
              keyboardType="numeric"
              editable={!isLoading}
            />
            <ChoiceRow
              options={BUDGET_PRESETS}
              isActive={(option) => option.value === budget}
              onSelect={(option) =>
                setBudgetText(option.value === null ? '' : String(option.value))
              }
            />

            <Text style={styles.panelLabel}>Priorita</Text>
            <ChoiceRow
              options={PRIORITIES}
              isActive={(option) => option.value === priority}
              onSelect={(option) => setPriority(option.value)}
            />

            <Pressable
              accessibilityRole="button"
              disabled={!canSubmit}
              onPress={handleSearch}
              style={({ pressed }) => [
                styles.primaryButton,
                pressed && styles.primaryButtonPressed,
                !canSubmit && styles.primaryButtonDisabled,
              ]}
            >
              <Text style={styles.primaryButtonText}>Prozkoumat trh</Text>
            </Pressable>
          </View>

          {isLoading && (
            <View style={styles.loadingBox}>
              <ActivityIndicator size="large" color={C.green} />
              <Text style={styles.loadingText}>{PIPELINE_STAGES[stageIndex]}</Text>
              <Text style={styles.loadingHint}>
                Fáze {stageIndex + 1} ze {PIPELINE_STAGES.length}
              </Text>
            </View>
          )}

          {!isLoading && errorMessage && (
            <View style={styles.errorBox}>
              <Text style={styles.errorTitle}>Něco se nepovedlo</Text>
              <Text style={styles.errorText}>{errorMessage}</Text>
              <Pressable
                accessibilityRole="button"
                onPress={handleSearch}
                style={({ pressed }) => [styles.retryButton, pressed && styles.retryButtonPressed]}
              >
                <Text style={styles.retryButtonText}>Zkusit znovu</Text>
              </Pressable>
            </View>
          )}

          {!isLoading && !errorMessage && !report && (
            <View style={styles.placeholderBox}>
              <Text style={styles.placeholderTitle}>
                {hasSearched ? 'Žádné karty k zobrazení' : 'Tři karty z otevřeného webu'}
              </Text>
              <Text style={styles.placeholderText}>
                Agent projde e-shopy, EU sklady i výrobce s doručením do Rakouska.
                Nechá jen certifikované kusy s přímým odkazem a aktuální cenou.
                U každé karty jde otevřít nabídka a zvlášť zkontrolovat bazar na Willhabenu.
              </Text>
            </View>
          )}

          {!isLoading && report && (
            <>
              <View style={styles.supervisorBox}>
                <Text style={styles.supervisorLabel}>AUDITOR</Text>
                <Text style={styles.supervisorText}>
                  Auditor: {report.supervisor_verdict}
                </Text>
              </View>

              {report.items.map((item, index) => (
                <ProductCard
                  key={`${item.badge ?? 'karta'}-${index}`}
                  item={item}
                  onOpenOffers={handleOpenOffers}
                />
              ))}

              <Text style={styles.disclaimer}>
                Cena je odhad z analýzy. Koupit / Nabídky otevře Google Shopping v Rakousku,
                takže se dostaneš na reálné e-shopy. Geizhals a Idealo jsou srovnání,
                Willhaben je kontrola bazaru.
              </Text>
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: C.background,
    paddingTop: Platform.OS === 'android' ? RNStatusBar.currentHeight ?? 0 : 0,
  },
  flex: {
    flex: 1,
  },
  header: {
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: C.border,
  },
  headerTitle: {
    color: C.text,
    fontSize: 26,
    fontWeight: '800',
    letterSpacing: 0.3,
  },
  headerSubtitle: {
    color: C.muted,
    fontSize: 13,
    marginTop: 4,
  },
  scrollContent: {
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 40,
  },
  panel: {
    backgroundColor: C.panel,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: C.border,
    padding: 16,
  },
  panelLabel: {
    color: C.muted,
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.9,
    textTransform: 'uppercase',
    marginBottom: 7,
  },
  input: {
    backgroundColor: '#0f172a',
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 11,
    paddingHorizontal: 13,
    paddingVertical: Platform.OS === 'ios' ? 13 : 10,
    color: C.text,
    fontSize: 15,
    marginBottom: 14,
  },
  choiceRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 16,
  },
  choiceChip: {
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: '#0f172a',
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  choiceChipActive: {
    borderColor: C.green,
    backgroundColor: '#14361f',
  },
  choiceChipPressed: {
    opacity: 0.7,
  },
  choiceText: {
    color: C.muted,
    fontSize: 13,
    fontWeight: '600',
  },
  choiceTextActive: {
    color: C.green,
  },
  primaryButton: {
    backgroundColor: C.green,
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 2,
  },
  primaryButtonPressed: {
    backgroundColor: '#16a34a',
  },
  primaryButtonDisabled: {
    backgroundColor: '#1f3d2b',
  },
  primaryButtonText: {
    color: '#052e16',
    fontSize: 16,
    fontWeight: '800',
    letterSpacing: 0.4,
  },
  loadingBox: {
    paddingVertical: 48,
    alignItems: 'center',
  },
  loadingText: {
    color: C.text,
    fontSize: 15,
    marginTop: 18,
    textAlign: 'center',
    paddingHorizontal: 20,
  },
  loadingHint: {
    color: C.muted,
    fontSize: 12,
    marginTop: 7,
  },
  errorBox: {
    backgroundColor: '#2a1519',
    borderWidth: 1,
    borderColor: '#b91c3c',
    borderRadius: 14,
    padding: 16,
    marginTop: 16,
  },
  errorTitle: {
    color: C.red,
    fontSize: 15,
    fontWeight: '700',
    marginBottom: 6,
  },
  errorText: {
    color: '#e2e8f0',
    fontSize: 14,
    lineHeight: 20,
  },
  retryButton: {
    marginTop: 14,
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderColor: '#b91c3c',
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 9,
  },
  retryButtonPressed: {
    backgroundColor: '#3b1d22',
  },
  retryButtonText: {
    color: C.red,
    fontSize: 14,
    fontWeight: '600',
  },
  placeholderBox: {
    paddingVertical: 32,
    paddingHorizontal: 4,
  },
  placeholderTitle: {
    color: C.text,
    fontSize: 17,
    fontWeight: '700',
    marginBottom: 8,
  },
  placeholderText: {
    color: C.muted,
    fontSize: 14,
    lineHeight: 21,
  },
  supervisorBox: {
    marginTop: 18,
    marginBottom: 16,
    backgroundColor: '#0d2a1a',
    borderWidth: 1,
    borderColor: C.green,
    borderRadius: 14,
    padding: 14,
  },
  supervisorLabel: {
    color: C.green,
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 1.2,
    marginBottom: 6,
  },
  supervisorText: {
    color: '#dcfce7',
    fontSize: 13,
    lineHeight: 19,
  },
  card: {
    borderWidth: 1.5,
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 9,
    marginBottom: 10,
  },
  cardChip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  cardChipText: {
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.8,
  },
  cardBadge: {
    fontSize: 11,
    fontWeight: '700',
    flexShrink: 1,
  },
  cardTitle: {
    color: C.text,
    fontSize: 19,
    fontWeight: '800',
    lineHeight: 25,
  },
  cardOriginal: {
    color: C.muted,
    fontSize: 13,
    fontStyle: 'italic',
    marginTop: 3,
  },
  priceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 12,
    marginTop: 12,
    marginBottom: 6,
  },
  originRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 12,
  },
  originChip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  originChipText: {
    fontSize: 12,
    fontWeight: '800',
  },
  shipText: {
    color: C.muted,
    fontSize: 13,
    fontWeight: '600',
  },
  priceCaption: {
    color: C.muted,
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  price: {
    fontSize: 32,
    fontWeight: '800',
  },
  usedChip: {
    backgroundColor: '#0f172a',
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 10,
    paddingHorizontal: 11,
    paddingVertical: 6,
  },
  usedChipLabel: {
    color: C.muted,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 0.8,
  },
  usedChipValue: {
    color: C.text,
    fontSize: 14,
    fontWeight: '700',
    marginTop: 1,
  },
  sectionLabel: {
    color: C.muted,
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.9,
    textTransform: 'uppercase',
    marginTop: 14,
    marginBottom: 7,
  },
  bulletRow: {
    flexDirection: 'row',
    marginBottom: 5,
  },
  bulletSymbol: {
    fontSize: 14,
    fontWeight: '800',
    width: 16,
    lineHeight: 20,
  },
  bulletText: {
    flex: 1,
    color: '#dbe3ed',
    fontSize: 14,
    lineHeight: 20,
  },
  liquidityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  meterTrack: {
    flexDirection: 'row',
    gap: 3,
  },
  meterSegment: {
    width: 20,
    height: 6,
    borderRadius: 3,
  },
  liquidityText: {
    fontSize: 13,
    fontWeight: '700',
    flexShrink: 1,
  },
  targetText: {
    color: '#dbe3ed',
    fontSize: 14,
    lineHeight: 20,
  },
  linkRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 18,
  },
  offerButton: {
    flexGrow: 1,
    flexBasis: '46%',
    borderWidth: 1.5,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 8,
    alignItems: 'center',
  },
  offerButtonPrimary: {
    borderWidth: 0,
    flexBasis: '100%',
  },
  offerButtonDisabled: {
    opacity: 0.4,
  },
  offerButtonText: {
    fontSize: 14,
    fontWeight: '800',
    letterSpacing: 0.2,
    textAlign: 'center',
  },
  offerButtonPrimaryText: {
    color: '#f8fafc',
    fontSize: 14,
    fontWeight: '800',
    letterSpacing: 0.2,
    textAlign: 'center',
  },
  disclaimer: {
    color: '#64748b',
    fontSize: 12,
    lineHeight: 18,
    textAlign: 'center',
    marginTop: 4,
  },
});
