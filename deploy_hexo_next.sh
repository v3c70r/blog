
hexo init blog
cd blog
cp ../_config.yml ./
# Remove hello world post
rm source/_posts/*
# Copy post
cp ../_posts/* source/_posts/
# Install Next theme
git clone https://github.com/theme-next/hexo-theme-next themes/next      
cp ../_next_config.yml themes/next/_config.yml

# Config pandoc renderer
npm un hexo-renderer-marked
npm i hexo-renderer-pandoc --save
npm i hexo-deployer-git --save

# push to blog repo
git config --global user.email "gh@qgu.com"
git config --global user.name "Qing Gu"
hexo generate
hexo deploy


