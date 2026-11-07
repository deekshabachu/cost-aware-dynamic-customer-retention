import { ArrowLeft, Check, Plus } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ErrorState, LoadingState } from "../components/PageState";
import { ProductArtwork } from "../components/ProductArtwork";
import { formatRupees } from "../data/products";
import { useCart } from "../context/CartContext";

export function ProductDetailsPage() {
  const { productId } = useParams();
  const navigate = useNavigate();
  const { addProduct, catalogue, catalogueLoading, catalogueError, reloadCatalogue } = useCart();
  const product = catalogue.find((item) => item.id === productId);

  if (catalogueLoading) return <section className="page-shell simple-page"><LoadingState label="Loading product details" /></section>;
  if (catalogueError) return <section className="page-shell simple-page"><ErrorState message={catalogueError} retry={reloadCatalogue} /></section>;

  if (!product) {
    return <section className="page-shell simple-page"><span className="eyebrow">Not in this collection</span><h1>We couldn't find that piece.</h1><Link className="button button-dark" to="/">Back to the collection</Link></section>;
  }

  return (
    <section className="page-shell product-detail-page">
      <button className="back-link" onClick={() => navigate(-1)}><ArrowLeft size={16} /> Back</button>
      <div className="product-detail-layout">
        <div className="detail-art-wrap"><ProductArtwork product={product} /></div>
        <div className="detail-copy">
          <span className="eyebrow">{product.category} · {product.packSize}</span>
          <h1>{product.name}</h1>
          <div className="detail-price">{formatRupees(product.price)}</div>
          <p className="detail-description">{product.description}</p>
          <div className="detail-rule" />
          <div className="detail-benefits"><span><Check size={15} /> Product information</span><span><Check size={15} /> Price shown in INR</span></div>
          <button className="button button-dark add-detail-button" onClick={() => addProduct(product)}><Plus size={17} /> Add to bag</button>
        </div>
      </div>
    </section>
  );
}
