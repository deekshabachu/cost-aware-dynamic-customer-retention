import type { Product } from "../data/products";

export function ProductArtwork({ product, compact = false }: { product: Product; compact?: boolean }) {
  return (
    <div className={`product-art art-${product.tone} ${compact ? "is-compact" : ""}`} aria-label={`${product.name} illustration`} role="img">
      <span className="art-orbit art-orbit-one" />
      <span className="art-orbit art-orbit-two" />
      <span className="art-sun" />
      <span className="art-object">{product.emoji}</span>
      <span className="art-caption">{product.packSize} · SAMPLE ITEM</span>
    </div>
  );
}
