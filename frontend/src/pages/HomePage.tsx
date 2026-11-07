import { ArrowUpRight } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorState, LoadingState } from "../components/PageState";
import { ProductCard } from "../components/ProductCard";
import { useCart } from "../context/CartContext";
import { categories } from "../data/products";

export function HomePage() {
  const { catalogue, catalogueLoading, catalogueError, reloadCatalogue } = useCart();
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeCategory, setActiveCategory] = useState<string>("All");
  const search = searchParams.get("q") ?? "";

  const visibleProducts = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("en-IN");
    return catalogue.filter((product) => {
      const categoryMatches = activeCategory === "All" || product.category === activeCategory;
      const searchMatches = !query || `${product.name} ${product.category} ${product.packSize}`
        .toLocaleLowerCase("en-IN").includes(query);
      return categoryMatches && searchMatches;
    });
  }, [catalogue, activeCategory, search]);

  const updateSearch = (value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set("q", value);
    else next.delete("q");
    setSearchParams(next, { replace: true });
  };

  return (
    <section className="page-shell storefront-page" id="catalog">

      <div className="catalog-heading">
        <div>
          <span className="eyebrow">LittleLeaf neighbourhood shop</span>
          <h1>Everyday essentials</h1>
        </div>
        <Link className="retention-text-link" to="/retention-offer">Your retention offer <ArrowUpRight size={15} /></Link>
      </div>

      <nav className="category-tabs" aria-label="Filter products by category">
        {categories.map((category) => (
          <button
            type="button"
            className={activeCategory === category ? "active" : ""}
            key={category}
            onClick={() => setActiveCategory(category)}
            aria-pressed={activeCategory === category}
          >
            {category}
          </button>
        ))}
      </nav>


      <div className="catalog-results-heading">
        <h2>{activeCategory === "All" ? "Shop all products" : activeCategory}</h2>
        {!catalogueLoading && !catalogueError && <span>{visibleProducts.length} items</span>}
      </div>

      {catalogueLoading && <LoadingState label="Loading products" />}
      {!catalogueLoading && catalogueError && <ErrorState message={catalogueError} retry={reloadCatalogue} />}
      {!catalogueLoading && !catalogueError && catalogue.length === 0 && (
        <div className="catalog-empty"><h3>No products are available</h3><p>The product catalogue is currently empty.</p></div>
      )}
      {!catalogueLoading && !catalogueError && catalogue.length > 0 && visibleProducts.length > 0 && (
        <div className="product-grid">{visibleProducts.map((product) => <ProductCard key={product.id} product={product} />)}</div>
      )}
      {!catalogueLoading && !catalogueError && catalogue.length > 0 && visibleProducts.length === 0 && (
        <div className="catalog-empty">
          <h3>No products found</h3>
          <p>Try another product name or choose a different category.</p>
          <button type="button" className="button button-outline" onClick={() => { updateSearch(""); setActiveCategory("All"); }}>Show all products</button>
        </div>
      )}
    </section>
  );
}
