document.addEventListener("DOMContentLoaded", function() {
  function initializeSlideshow(slideshowId) {
    let slideIndex = 0;
    const slideshow = document.getElementById(slideshowId);
    showSlides(slideshowId);

    const prevButton = slideshow.querySelector(".prev");
    const nextButton = slideshow.querySelector(".next");

    prevButton.addEventListener("click", function() {
      plusSlides(-1, slideshowId);
    });

    nextButton.addEventListener("click", function() {
      plusSlides(1, slideshowId);
    });

    function showSlides(slideshowId) {
      const slides = document.getElementById(slideshowId).getElementsByClassName("slides");

      if (slideIndex >= slides.length) { slideIndex = 0 }
      if (slideIndex < 0) { slideIndex = slides.length - 1 }

      for (let i = 0; i < slides.length; i++) {
        slides[i].style.display = "none";
      }

      console.log(slideIndex)
      slides[slideIndex].style.display = "block";

    }

    function plusSlides(n, slideshowId) {
      slideIndex += n;
      showSlides(slideshowId);
    }
  }

  for (i = 1; i <= document.getElementsByClassName("slideshow-container").length; i++) {
    slideshowId = 'slideshow' + i;
    console.log(slideshowId)
    initializeSlideshow(slideshowId);
  }

});
