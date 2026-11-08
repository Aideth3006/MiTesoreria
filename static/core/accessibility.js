(() => {
  const form = document.querySelector(".movement-entry-form");
  const select = form?.querySelector("select[name='cash_box']");
  const output = document.getElementById("cashbox-balance");
  if (form && select && output) {
    select.addEventListener("change", async () => {
      if (!select.value) {
        output.textContent = "Selecciona una caja para consultar su saldo.";
        return;
      }
      output.textContent = "Consultando saldo…";
      try {
        const url = new URL(form.dataset.balanceUrl, window.location.origin);
        url.searchParams.set("cash_box_id", select.value);
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error("Balance no disponible");
        const data = await response.json();
        output.textContent = `Saldo actual: $${data.balance}`;
      } catch {
        output.textContent = "No se pudo consultar el saldo. Actualiza la página e inténtalo de nuevo.";
      }
    });
  }
})();
