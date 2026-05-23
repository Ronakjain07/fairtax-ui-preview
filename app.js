/* ===== FairTax — App.js ===== */
/* Three.js Particle Hero + GSAP ScrollTrigger + Lenis Smooth Scroll */

(function () {
  'use strict';

  // ===== LENIS SMOOTH SCROLL =====
  const lenis = new Lenis({ duration: 1.2, easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)) });
  function raf(time) { lenis.raf(time); requestAnimationFrame(raf); }
  requestAnimationFrame(raf);
  // Sync Lenis with GSAP ScrollTrigger
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);

  // ===== THREE.JS PARTICLE HERO =====
  const canvas = document.getElementById('hero-canvas');
  if (canvas) {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Particles
    const particleCount = 800;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const velocities = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount * 3; i += 3) {
      positions[i] = (Math.random() - 0.5) * 20;
      positions[i + 1] = (Math.random() - 0.5) * 20;
      positions[i + 2] = (Math.random() - 0.5) * 10;
      velocities[i] = (Math.random() - 0.5) * 0.005;
      velocities[i + 1] = (Math.random() - 0.5) * 0.005;
      velocities[i + 2] = (Math.random() - 0.5) * 0.002;
    }
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    const material = new THREE.PointsMaterial({
      color: 0x3b82f6, size: 0.04, transparent: true, opacity: 0.6,
      blending: THREE.AdditiveBlending, sizeAttenuation: true
    });
    const points = new THREE.Points(geometry, material);
    scene.add(points);

    // Connection lines
    const lineGeo = new THREE.BufferGeometry();
    const linePositions = new Float32Array(particleCount * particleCount * 3);
    lineGeo.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));
    const lineMat = new THREE.LineBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.08, blending: THREE.AdditiveBlending });
    const lines = new THREE.LineSegments(lineGeo, lineMat);
    scene.add(lines);

    camera.position.z = 8;
    let mouseX = 0, mouseY = 0;
    document.addEventListener('mousemove', (e) => {
      mouseX = (e.clientX / window.innerWidth - 0.5) * 2;
      mouseY = (e.clientY / window.innerHeight - 0.5) * 2;
    });

    function animateThree() {
      requestAnimationFrame(animateThree);
      const pos = geometry.attributes.position.array;
      for (let i = 0; i < particleCount * 3; i += 3) {
        pos[i] += velocities[i];
        pos[i + 1] += velocities[i + 1];
        pos[i + 2] += velocities[i + 2];
        if (Math.abs(pos[i]) > 10) velocities[i] *= -1;
        if (Math.abs(pos[i + 1]) > 10) velocities[i + 1] *= -1;
        if (Math.abs(pos[i + 2]) > 5) velocities[i + 2] *= -1;
      }
      geometry.attributes.position.needsUpdate = true;

      // Update lines - connect nearby particles
      let lineIdx = 0;
      const lp = lineGeo.attributes.position.array;
      const maxDist = 2.5;
      for (let i = 0; i < Math.min(particleCount, 100); i++) {
        for (let j = i + 1; j < Math.min(particleCount, 100); j++) {
          const dx = pos[i * 3] - pos[j * 3];
          const dy = pos[i * 3 + 1] - pos[j * 3 + 1];
          const dz = pos[i * 3 + 2] - pos[j * 3 + 2];
          const d = dx * dx + dy * dy + dz * dz;
          if (d < maxDist * maxDist && lineIdx < linePositions.length - 6) {
            lp[lineIdx++] = pos[i * 3]; lp[lineIdx++] = pos[i * 3 + 1]; lp[lineIdx++] = pos[i * 3 + 2];
            lp[lineIdx++] = pos[j * 3]; lp[lineIdx++] = pos[j * 3 + 1]; lp[lineIdx++] = pos[j * 3 + 2];
          }
        }
      }
      for (let i = lineIdx; i < Math.min(lineIdx + 600, linePositions.length); i++) lp[i] = 0;
      lineGeo.attributes.position.needsUpdate = true;
      lineGeo.setDrawRange(0, lineIdx / 3);

      camera.position.x += (mouseX * 0.5 - camera.position.x) * 0.02;
      camera.position.y += (-mouseY * 0.5 - camera.position.y) * 0.02;
      camera.lookAt(scene.position);
      points.rotation.y += 0.0005;
      renderer.render(scene, camera);
    }
    animateThree();

    window.addEventListener('resize', () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });
  }

  // ===== NAVBAR =====
  const navbar = document.getElementById('navbar');
  let lastScroll = 0;
  window.addEventListener('scroll', () => {
    const current = window.pageYOffset;
    if (current > lastScroll && current > 100) {
      navbar.classList.add('hidden');
    } else {
      navbar.classList.remove('hidden');
    }
    lastScroll = current;
  });

  // Mobile menu
  const hamburger = document.getElementById('hamburger');
  const navLinks = document.getElementById('navLinks');
  if (hamburger) {
    hamburger.addEventListener('click', () => navLinks.classList.toggle('active'));
    navLinks.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => navLinks.classList.remove('active'));
    });
  }

  // ===== GSAP ANIMATIONS =====
  gsap.registerPlugin(ScrollTrigger);

  // Hero entrance
  const heroTl = gsap.timeline({ defaults: { ease: 'power3.out' } });
  heroTl
    .from('.hero-badge', { opacity: 0, y: 30, duration: 0.8, delay: 0.3 })
    .from('.hero h1', { opacity: 0, y: 50, duration: 1 }, '-=0.4')
    .from('.hero-desc', { opacity: 0, y: 40, duration: 0.8 }, '-=0.6')
    .from('.hero-actions', { opacity: 0, y: 40, duration: 0.8 }, '-=0.5')
    .from('.hero-stats', { opacity: 0, y: 60, duration: 1 }, '-=0.4');

  // Counter animation
  function animateCounters() {
    document.querySelectorAll('.stat-number').forEach(el => {
      const target = parseFloat(el.dataset.target);
      const suffix = el.dataset.suffix || '';
      const isDecimal = el.dataset.decimal === 'true';
      const obj = { val: 0 };
      gsap.to(obj, {
        val: target, duration: 2.5, ease: 'power2.out',
        onUpdate: () => {
          if (isDecimal) el.textContent = obj.val.toFixed(1) + suffix;
          else if (target >= 100000) el.textContent = Math.floor(obj.val / 100000) + 'L' + suffix;
          else el.textContent = Math.floor(obj.val) + suffix;
        }
      });
    });
  }
  ScrollTrigger.create({ trigger: '.hero-stats', start: 'top 85%', once: true, onEnter: animateCounters });

  // Generic section reveals
  gsap.utils.toArray('.step-card').forEach((el, i) => {
    gsap.from(el, {
      scrollTrigger: { trigger: el, start: 'top 85%', once: true },
      opacity: 0, y: 60, rotateX: 8, duration: 0.8, delay: i * 0.15, ease: 'power3.out'
    });
  });

  gsap.utils.toArray('.service-card').forEach((el, i) => {
    gsap.from(el, {
      scrollTrigger: { trigger: el, start: 'top 88%', once: true },
      opacity: 0, y: 50, scale: 0.95, duration: 0.7, delay: i * 0.1, ease: 'power3.out'
    });
  });

  // Section headers
  gsap.utils.toArray('.section-header, .about-content, .referral-content').forEach(el => {
    gsap.from(el, {
      scrollTrigger: { trigger: el, start: 'top 82%', once: true },
      opacity: 0, y: 50, duration: 0.9, ease: 'power3.out'
    });
  });

  // About image
  gsap.from('.about-image', {
    scrollTrigger: { trigger: '.about-image', start: 'top 80%', once: true },
    opacity: 0, x: -60, duration: 1, ease: 'power3.out'
  });

  // Free filing cards
  gsap.utils.toArray('.free-filing-card').forEach((el, i) => {
    gsap.from(el, {
      scrollTrigger: { trigger: el, start: 'top 85%', once: true },
      opacity: 0, y: 50, duration: 0.7, delay: i * 0.12, ease: 'power3.out'
    });
  });

  // Referral image
  gsap.from('.referral-image', {
    scrollTrigger: { trigger: '.referral-image', start: 'top 80%', once: true },
    opacity: 0, x: 60, duration: 1, ease: 'power3.out'
  });

  // Milestone cards
  gsap.utils.toArray('.milestone-card').forEach((el, i) => {
    gsap.from(el, {
      scrollTrigger: { trigger: el, start: 'top 88%', once: true },
      opacity: 0, y: 40, scale: 0.9, duration: 0.6, delay: i * 0.1, ease: 'back.out(1.5)'
    });
  });

  // CTA section
  gsap.from('.cta-section .section-title', {
    scrollTrigger: { trigger: '.cta-section', start: 'top 80%', once: true },
    opacity: 0, y: 50, duration: 0.9, ease: 'power3.out'
  });
  gsap.from('.cta-section .section-desc', {
    scrollTrigger: { trigger: '.cta-section', start: 'top 78%', once: true },
    opacity: 0, y: 40, duration: 0.8, delay: 0.2, ease: 'power3.out'
  });
  gsap.from('.cta-section .btn-primary', {
    scrollTrigger: { trigger: '.cta-section', start: 'top 75%', once: true },
    opacity: 0, y: 40, duration: 0.8, delay: 0.4, ease: 'power3.out'
  });

  // Parallax on about image
  gsap.to('.about-image img', {
    scrollTrigger: {
      trigger: '.about-image', start: 'top bottom', end: 'bottom top', scrub: 1
    },
    y: -40, ease: 'none'
  });

})();
