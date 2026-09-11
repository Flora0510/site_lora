document.addEventListener('DOMContentLoaded', function () {
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var isOpen = nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });
  }

  var boutonsFiltre = document.querySelectorAll('.filtre-auteures .filtre-btn');
  if (boutonsFiltre.length) {
    boutonsFiltre.forEach(function (bouton) {
      bouton.addEventListener('click', function () {
        boutonsFiltre.forEach(function (b) { b.classList.remove('active'); });
        bouton.classList.add('active');
        var filtre = bouton.getAttribute('data-filtre');

        document.querySelectorAll('[data-auteures]').forEach(function (carte) {
          var auteures = (carte.getAttribute('data-auteures') || '').split(' ');
          var visible = filtre === 'tous' || auteures.indexOf(filtre) !== -1;
          carte.style.display = visible ? '' : 'none';
        });

        // Masque les sections (ex. "Dès 8 ans") qui n'ont plus aucune carte visible
        document.querySelectorAll('.section-filtrable').forEach(function (section) {
          var cartes = section.querySelectorAll('[data-auteures]');
          var auMoinsUneVisible = false;
          cartes.forEach(function (carte) {
            if (carte.style.display !== 'none') { auMoinsUneVisible = true; }
          });
          section.style.display = (cartes.length === 0 || auMoinsUneVisible) ? '' : 'none';
        });
      });
    });
  }
});
