import ListingModal from "@/components/Listings/ListingModal";

/** Intercepts /listing/[id] when it is reached from inside the app, so a click
 * in the feed opens the property over the search instead of replacing it. A
 * direct visit or a refresh skips this file and renders app/listing/[id]. */
export default function InterceptedListingPage({ params }: { params: { id: string } }) {
  return <ListingModal id={decodeURIComponent(params.id)} />;
}
