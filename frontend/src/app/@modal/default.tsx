/** No modal for routes that are not an intercepted listing. Required by the
 * @modal parallel slot: without it, a hard navigation to any other route has
 * nothing to render in the slot and Next.js 404s the whole page. */
export default function DefaultModal() {
  return null;
}
