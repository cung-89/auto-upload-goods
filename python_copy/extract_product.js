() => {
  // Read product fields only. Do not export login state, tracking parameters or cookies.
  const root = window.__ICE_APP_CONTEXT__?.loaderData?.home?.data?.res;
  if (!root?.item?.itemId) return null;
  const item = root.item;
  const base = root.skuBase || {};
  return {
    attributes: [
      ...Array.from(document.querySelectorAll('.paramsInfoArea [class*="emphasisParamsInfoItem--"]')).map(n => ({
        name: n.querySelector('[class*="emphasisParamsInfoItemSubTitle--"]')?.textContent.trim(),
        value: n.querySelector('[class*="emphasisParamsInfoItemTitle--"]')?.textContent.trim(),
      })),
      ...Array.from(document.querySelectorAll('.paramsInfoArea [class*="generalParamsInfoItem--"]')).map(n => ({
        name: n.querySelector('[class*="generalParamsInfoItemTitle--"]')?.textContent.trim(),
        value: n.querySelector('[class*="generalParamsInfoItemSubTitle--"]')?.textContent.trim(),
      })),
    ].filter(p => p.name && p.value),
    item: {
      itemId: String(item.itemId), title: item.title,
      images: item.images || root.componentsVO?.headImageVO?.images || [],
      descriptionUrl: item.pcADescUrl || null,
    },
    properties: (base.props || []).map(p => ({
      id: String(p.pid), name: p.name,
      values: (p.values || []).map(v => ({id: String(v.vid), name: v.name, image: v.image || null})),
    })),
    skus: (base.skus || []).map(s => ({id: String(s.skuId), path: s.propPath || ''})),
    offers: Object.fromEntries(Object.entries(root.skuCore?.sku2info || {}).map(([id, s]) => [id, {
      priceText: s.price?.priceText ?? null,
      priceMoney: s.price?.priceMoney ?? null,
      priceLabel: s.price?.priceTitle ?? null,
      displayedQuantity: s.quantity ?? null,
      moreQuantity: s.moreQuantity === true || s.moreQuantity === 'true',
    }])),
  };
}
