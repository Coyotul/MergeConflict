// Orchestrator-specific formatting (decimal strings, never parsed to float)

/**
 * Format a decimal string as money without float conversion.
 * Groups integer digits with commas, preserves the exact decimal part, appends currency.
 * @example formatMoneyString("15000.50", "RON") => "15,000.50 RON"
 * @example formatMoneyString("1234", "RON") => "1,234 RON"
 */
export function formatMoneyString(amount: string, currency: string): string {
  const [integerPart, decimalPart] = amount.split(".");
  const grouped = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const formatted = decimalPart !== undefined ? `${grouped}.${decimalPart}` : grouped;
  return `${formatted} ${currency}`;
}
