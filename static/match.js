// Match page interactions: play goal sound, show GIF lightbox
document.addEventListener('DOMContentLoaded', function(){
  const goalSfx = document.getElementById('goal-sfx');
  const crowdSfx = document.getElementById('crowd-sfx');

  document.querySelectorAll('.play-goal').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      if(goalSfx){
        goalSfx.currentTime = 0;
        goalSfx.play();
      }
      // small crowd cheer after goal
      if(crowdSfx){
        setTimeout(()=>{ crowdSfx.currentTime=0; crowdSfx.play(); }, 200);
      }
    });
  });

  // Lightbox for GIFs
  const modal = document.getElementById('gif-modal');
  const modalImg = document.getElementById('gif-modal-img');
  document.querySelectorAll('.gif-thumb').forEach(img=>{
    img.addEventListener('click', ()=>{
      modalImg.src = img.dataset.full;
      modal.classList.remove('hidden');
    });
  });
  document.getElementById('gif-modal-close').addEventListener('click', ()=>{
    modal.classList.add('hidden');
    modalImg.src = '';
  });
});